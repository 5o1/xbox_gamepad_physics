import {copyFile, lstat, mkdir, mkdtemp, readdir, rename, rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {dirname, join} from 'node:path';
import {randomUUID} from 'node:crypto';
import {fileURLToPath} from 'node:url';

/**
 * Test/capture scripts always write a complete staging set first.  With
 * --publish, only staged files are replaced after validation; unrelated files
 * in the target directory are deliberately left alone.  This is a rollback-
 * protected multi-file replacement, not an atomic directory swap across a
 * process or power failure.
 */
export async function artifactOutput({publish, publishUrl, temporaryPrefix}) {
  const directory = await mkdtemp(join(tmpdir(), temporaryPrefix));
  await mkdir(directory, {recursive: true});
  const publishDirectory = publish ? fileURLToPath(publishUrl) : null;
  let finalized = false;

  async function collect(root, relative = '') {
    const files = [];
    for (const entry of await readdir(join(root, relative), {withFileTypes: true})) {
      const child = join(relative, entry.name);
      if (entry.isDirectory()) files.push(...await collect(root, child));
      else if (entry.isFile()) files.push(child);
      else throw new Error(`Refusing to publish non-regular artifact: ${child}`);
    }
    return files;
  }

  async function finalize({files} = {}) {
    if (finalized) throw new Error('Artifact output already finalized');
    const stagedFiles = await collect(directory);
    let publishFiles = stagedFiles;
    if (files !== undefined) {
      if (!Array.isArray(files) || files.length === 0
          || files.some(relative => typeof relative !== 'string')) {
        throw new Error('Selected artifact files must be a non-empty string array');
      }
      if (new Set(files).size !== files.length) {
        throw new Error('Selected artifact files must not contain duplicates');
      }
      const staged = new Set(stagedFiles);
      for (const relative of files) {
        if (!staged.has(relative)) {
          throw new Error(`Selected artifact is not a staged regular file: ${relative}`);
        }
      }
      publishFiles = [...files];
    }
    if (!publish) {
      finalized = true;
      return;
    }
    const token = randomUUID(), prepared = [], backups = [], committed = [];
    try {
      for (const relative of publishFiles) {
        const target = join(publishDirectory, relative);
        await mkdir(dirname(target), {recursive: true});
        const temporary = `${target}.publish-${token}.tmp`;
        await copyFile(join(directory, relative), temporary);
        prepared.push({target, temporary, backup: `${target}.publish-${token}.bak`});
      }
      for (const item of prepared) {
        try {
          const existing=await lstat(item.target);
          if(!existing.isFile())throw new Error(`Refusing to replace non-regular artifact: ${item.target}`);
        } catch (error) {
          if (error.code !== 'ENOENT') throw error;
        }
      }
      // Nothing under build/experiments/ changes until every staged file has a complete
      // same-filesystem temporary copy.
      for (const item of prepared) {
        try {
          await rename(item.target, item.backup);
          backups.push(item);
        } catch (error) {
          if (error.code !== 'ENOENT') throw error;
        }
      }
      for (const item of prepared) {
        await rename(item.temporary, item.target);
        committed.push(item);
      }
      finalized = true;
    } catch (error) {
      for (const item of committed.reverse()) await rm(item.target, {force: true}).catch(()=>{});
      for (const item of backups.reverse()) await rename(item.backup, item.target).catch(()=>{});
      for (const item of prepared) await rm(item.temporary, {force: true}).catch(()=>{});
      throw error;
    }
    // Every staged replacement is now installed. Unmanaged files in the target
    // directory are outside this transaction. Backup cleanup is deliberately best-effort:
    // a cleanup failure must never trigger rollback after earlier backups have
    // already been deleted, because that could destroy both generations.
    const cleanupWarnings=[];
    for (const item of backups) {
      try { await rm(item.backup, {force:true}); }
      catch(error) { cleanupWarnings.push(`${item.backup}: ${error.message}`); }
    }
    if(cleanupWarnings.length)console.warn(JSON.stringify({artifact_cleanup_warnings:cleanupWarnings}));
    return {cleanupWarnings};
  }

  return {directory, published: publish, finalize};
}

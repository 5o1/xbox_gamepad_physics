import assert from 'node:assert/strict';
import test, {after} from 'node:test';
import {mkdtemp, mkdir, readFile, rm, writeFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {artifactOutput} from './artifact_output.mjs';


const temporaryPaths=[];
const track=path=>{temporaryPaths.push(path);return path;};
after(async()=>Promise.all(temporaryPaths.map(path=>rm(path,{recursive:true,force:true}))));


test('publish stages all files before replacing reviewed artifacts', async()=>{
  const root=track(await mkdtemp(join(tmpdir(),'xbox-artifact-output-test-')));
  const published=join(root,'published');
  await mkdir(published);
  await writeFile(join(published,'one.json'),'old');
  const output=await artifactOutput({
    publish:true,
    publishUrl:pathToFileURL(published+'/'),
    temporaryPrefix:'xbox-artifact-stage-',
  });
  track(output.directory);
  await writeFile(join(output.directory,'one.json'),'new');
  await writeFile(join(output.directory,'two.json'),'second');
  assert.equal(await readFile(join(published,'one.json'),'utf8'),'old');
  await output.finalize();
  assert.equal(await readFile(join(published,'one.json'),'utf8'),'new');
  assert.equal(await readFile(join(published,'two.json'),'utf8'),'second');
  await assert.rejects(output.finalize(),/already finalized/);
});

test('ordinary runs remain in an isolated temporary directory',async()=>{
  const output=await artifactOutput({publish:false,publishUrl:null,temporaryPrefix:'xbox-artifact-temp-'});
  track(output.directory);
  await writeFile(join(output.directory,'result.json'),'temporary');
  await output.finalize();
  assert.equal(await readFile(join(output.directory,'result.json'),'utf8'),'temporary');
});

test('a non-file target aborts before any reviewed artifact is replaced',async()=>{
  const root=track(await mkdtemp(join(tmpdir(),'xbox-artifact-output-reject-'))),published=join(root,'published');
  await mkdir(join(published,'z-target'),{recursive:true});
  await writeFile(join(published,'a.txt'),'reviewed');
  const output=await artifactOutput({publish:true,publishUrl:pathToFileURL(published+'/'),temporaryPrefix:'xbox-artifact-stage-'});
  track(output.directory);
  await writeFile(join(output.directory,'a.txt'),'replacement');
  await writeFile(join(output.directory,'z-target'),'not-a-directory');
  await assert.rejects(output.finalize(),/non-regular artifact/);
  assert.equal(await readFile(join(published,'a.txt'),'utf8'),'reviewed');
});

test('selected failure marker publishes without replacing successful artifacts',async()=>{
  const root=track(await mkdtemp(join(tmpdir(),'xbox-artifact-output-selected-')));
  const published=join(root,'published');
  await mkdir(published);
  await writeFile(join(published,'browser_last_attempt.json'),'old attempt');
  await writeFile(join(published,'browser_harness.json'),'last success');
  await writeFile(join(published,'browser.png'),'last success screenshot');
  const output=await artifactOutput({
    publish:true,
    publishUrl:pathToFileURL(published+'/'),
    temporaryPrefix:'xbox-artifact-stage-',
  });
  track(output.directory);
  await writeFile(join(output.directory,'browser_last_attempt.json'),'new failure');
  await writeFile(join(output.directory,'browser_harness.json'),'partial failure');
  await writeFile(join(output.directory,'browser.png'),'partial screenshot');

  await output.finalize({files:['browser_last_attempt.json']});

  assert.equal(await readFile(join(published,'browser_last_attempt.json'),'utf8'),'new failure');
  assert.equal(await readFile(join(published,'browser_harness.json'),'utf8'),'last success');
  assert.equal(await readFile(join(published,'browser.png'),'utf8'),'last success screenshot');
});

test('selected publishing fails closed for missing or duplicate staging names',async()=>{
  const root=track(await mkdtemp(join(tmpdir(),'xbox-artifact-output-selection-reject-')));
  const published=join(root,'published');
  await mkdir(published);
  const missing=await artifactOutput({
    publish:true,
    publishUrl:pathToFileURL(published+'/'),
    temporaryPrefix:'xbox-artifact-stage-',
  });
  track(missing.directory);
  await writeFile(join(missing.directory,'browser_last_attempt.json'),'failure');
  await assert.rejects(
    missing.finalize({files:['not-staged.json']}),
    /not a staged regular file/,
  );

  const duplicate=await artifactOutput({
    publish:true,
    publishUrl:pathToFileURL(published+'/'),
    temporaryPrefix:'xbox-artifact-stage-',
  });
  track(duplicate.directory);
  await writeFile(join(duplicate.directory,'browser_last_attempt.json'),'failure');
  await assert.rejects(
    duplicate.finalize({files:['browser_last_attempt.json','browser_last_attempt.json']}),
    /must not contain duplicates/,
  );
});

"""Lossless teleop records, with archived JSON Lines and a private block format.

XGPR v1: magic (8 bytes), uint32 little-endian JSON header length, UTF-8
header {schema_version, fields[{name, mode, type, shape}], original_header}.
An original session header is returned as the first dict, not a data step.
Each independently decodable block is BLK1 + <uint64 first_row, uint32 rows,
uint32 raw_bytes, uint32 compressed_bytes> + zlib payload + DONE. The terminal
END1 marker distinguishes a clean close from a killed writer. A missing/partial
block or terminal marker emits TruncatedRecordWarning after yielding all complete
blocks; malformed completed blocks raise ValueError. Flush commits complete
blocks to the OS (process-crash recovery, not a power-loss fsync guarantee).

Payload is columnar by top-level field. Fixed numeric trees use packed float64,
signed int64 and bool in little-endian order; tree schema records list/dict shape
and Python scalar types. A per-row tag records missing/fixed/length-prefixed JSON
fallback, preserving schema changes and int/float distinctions. Contacts, input
metadata and other variable fields use uint32 lengths plus UTF-8 JSON. Rare
state/audit/snapshot fields use row-indexed change events, with a fresh snapshot
at each block start, so no preceding block is needed for decoding. JSON preserves
arbitrary-sized integers and variable shapes without simulator defaults.

No final index is required: scan block headers (first row, count, offset) to
reconstruct a coarse index, including after a process crash. Every decoded row
has the keys, values and JSON types of the legacy JSON line; float64 is never
quantized. JSON Lines remains selectable through format='jsonl'.
"""
from __future__ import annotations

import copy
import json
import math
import multiprocessing
import os
import pickle
from pathlib import Path
import struct
from queue import Empty,Full
import warnings
import zlib

MAGIC=b'XGPR\x01\r\n\x1a'
BLOCK=struct.Struct('<QIII')
U32=struct.Struct('<I')
DEFAULT_FORMAT='binary'  # Real owner prefix measured 27.69x smaller than JSONL.
EVENT_FIELDS={'type','state','ghost','ghost_blocked','phase','secondary','frozen',
              'gripper_collision_groups','gripper_freeze','gamepad_frozen',
              'gamepad_transition','gamepad_collision_groups',
              'gamepad_articulation_count','gamepad_between_copy_contacts'}
VARIABLE_FIELDS={'contacts','geometry_blockers','input','input_events','cancelled_seqs','probe'}


class TruncatedRecordWarning(UserWarning):
    """Only complete blocks were yielded; an unfinished tail was discarded."""


def _json(value):
    return json.dumps(value,allow_nan=False,separators=(',',':'),ensure_ascii=True).encode('utf-8')


def _tree(value):
    kind=type(value)
    if kind is float:
        if not math.isfinite(value):raise ValueError('record floats must be finite')
        return 'float64'
    if kind is bool:return 'bool'
    if kind is int:return 'int64' if -(1<<63)<=value<(1<<63) else None
    if kind in (list,tuple):
        children=[_tree(x) for x in value]
        return {'list':children} if all(x is not None for x in children) else None
    if kind is dict:
        children=[[k,_tree(v)] for k,v in value.items()]
        return {'dict':children} if all(x is not None for _,x in children) else None
    # Strings/null inside a numeric struct are shape constants; a changed value
    # uses the explicit JSON fallback, never a silently updated schema.
    if kind in (str,type(None)):return {'literal':value}
    raise TypeError(f'unsupported record value {kind.__name__}')


def _codes(tree):
    if isinstance(tree,str):return {'float64':'d','int64':'q','bool':'?'}[tree]
    if 'literal' in tree:return ''
    return ''.join(_codes(t) for t in (tree['list'] if 'list' in tree else [t for _,t in tree['dict']]))


def _flatten(tree,value,values):
    if isinstance(tree,str):
        expected={'float64':float,'int64':int,'bool':bool}[tree]
        if type(value) is not expected:return False
        if tree=='int64' and not -(1<<63)<=value<(1<<63):return False
        if tree=='float64' and not math.isfinite(value):raise ValueError('record floats must be finite')
        values.append(value);return True
    if 'literal' in tree:return type(value) is type(tree['literal']) and value==tree['literal']
    if 'list' in tree:
        return isinstance(value,(list,tuple)) and len(value)==len(tree['list']) and all(_flatten(t,v,values) for t,v in zip(tree['list'],value))
    return type(value) is dict and list(value)==[k for k,_ in tree['dict']] and all(_flatten(t,value[k],values) for k,t in tree['dict'])


def _restore(tree,values):
    if isinstance(tree,str):return next(values)
    if 'literal' in tree:return tree['literal']
    if 'list' in tree:return [_restore(t,values) for t in tree['list']]
    return {k:_restore(t,values) for k,t in tree['dict']}


def _length(data):return U32.pack(len(data))+data


class JsonLinesWriter:
    """The original JSON Lines serialization, retained as a selectable writer."""
    def __init__(self,path):self.file=Path(path).open('w');self.closed=False
    def append(self,row):self.file.write(json.dumps(row,allow_nan=False)+'\n')
    def flush(self):self.file.flush()
    def close(self):
        if not self.closed:self.file.close();self.closed=True
    def __enter__(self):return self
    def __exit__(self,*exc):self.close()


class BinaryWriter:
    """Bounded blocks with a complete-block commit; no third-party dependencies."""
    def __init__(self,path,block_rows=128):
        if block_rows<1:raise ValueError('block_rows must be positive')
        self.file=Path(path).open('wb',buffering=0)
        self.block_rows=block_rows;self.rows=[];self.fields=None;self.original_header=None
        self.count=0;self.closed=False

    def _start(self,row):
        fields=[]
        for name,value in row.items():
            tree=_tree(value)
            mode='event' if name in EVENT_FIELDS else 'variable' if name in VARIABLE_FIELDS or tree is None else 'fixed'
            fields.append({'name':name,'mode':mode,'type':'json' if mode!='fixed' else 'struct',
                           'shape':tree if mode=='fixed' else None})
        self.fields=fields
        header={'schema_version':1,'byte_order':'little','compression':'zlib','block_rows':self.block_rows,
                'fields':fields,'original_header':self.original_header}
        self.file.write(MAGIC+_length(_json(header)))

    def append(self,row):
        if self.closed:raise ValueError('record writer is closed')
        if self.fields is None and row.get('type')=='header' and self.original_header is None:
            self.original_header=json.loads(_json(row));return
        if self.fields is None:self._start(row)
        # Keep record input independent of later caller mutation.
        self.rows.append(copy.deepcopy(row))
        if len(self.rows)>=self.block_rows:self.flush()

    def flush(self):
        if not self.rows:return
        payload=bytearray();names={f['name'] for f in self.fields}
        for field in self.fields:
            name=field['name'];mode=field['mode']
            if mode=='event':
                changes=[];previous=None
                for index,row in enumerate(self.rows):
                    present=name in row;data=_json(row[name]) if present else b''
                    state=(present,data)
                    if index==0 or state!=previous:changes.append((index,present,data));previous=state
                payload.extend(U32.pack(len(changes)))
                for index,present,data in changes:payload.extend(U32.pack(index)+bytes([present])+_length(data))
            elif mode=='fixed':
                packer=struct.Struct('<'+_codes(field['shape']))
                for row in self.rows:
                    values=[]
                    if name not in row:payload.append(0)
                    elif _flatten(field['shape'],row[name],values):payload.append(1);payload.extend(packer.pack(*values))
                    else:payload.append(2);payload.extend(_length(_json(row[name])))
            else:
                for row in self.rows:
                    present=name in row;payload.append(int(present))
                    if present:payload.extend(_length(_json(row[name])))
        # Fields introduced after the initial schema are explicit length-prefixed
        # per-row extensions; absent original fields remain absent.
        for row in self.rows:payload.extend(_length(_json({k:v for k,v in row.items() if k not in names})))
        compressed=zlib.compress(payload,1)
        self.file.write(b'BLK1'+BLOCK.pack(self.count,len(self.rows),len(payload),len(compressed))+compressed+b'DONE')
        self.count+=len(self.rows);self.rows.clear()

    def close(self):
        if self.closed:return
        try:
            if self.fields is None:self._start({})
            self.flush();self.file.write(b'END1')
        finally:self.file.close();self.closed=True
    def __enter__(self):return self
    def __exit__(self,*exc):self.close()


def _record_worker(path,blocks,errors,block_rows,parent_pid):
    """Compression has a separate GIL; complete-block commits survive parent loss."""
    try:
        with BinaryWriter(path,block_rows) as writer:
            while True:
                try:rows=blocks.get(timeout=.25)
                except Empty:
                    if os.getppid()!=parent_pid:return
                    continue
                if rows is None:return
                for row in rows:writer.append(pickle.loads(row))
                writer.flush()
    except BaseException as error:
        errors.put(f'{type(error).__name__}: {error}')
        raise


class BackgroundBinaryWriter:
    """Bounded asynchronous block encoding for the 250 Hz physics owner.

    The synchronous codec's measured worst append was 129 ms per block, so live
    physics copies a row and hands bounded batches to a dedicated process. Four
    pending blocks cap memory; persistent backpressure/worker failure raises,
    never drops rows. close() drains and waits for the complete END1 marker.
    """
    def __init__(self,path,block_rows=128):
        if block_rows<1:raise ValueError('block_rows must be positive')
        context=multiprocessing.get_context('spawn')
        self.blocks=context.Queue(maxsize=4);self.errors=context.Queue()
        self.process=context.Process(target=_record_worker,args=(str(path),self.blocks,self.errors,block_rows,os.getpid()),daemon=True)
        self.process.start();self.block_rows=block_rows;self.rows=[];self.closed=False

    def _check(self):
        try:error=self.errors.get_nowait()
        except Empty:error=None
        if error is not None:raise RuntimeError('record worker failed: '+error)
        if not self.process.is_alive():raise RuntimeError(f'record worker exited with code {self.process.exitcode}')

    def _send(self,rows):
        self._check()
        try:self.blocks.put(rows,timeout=5)
        except Full:raise RuntimeError('record worker cannot keep up; no records were silently dropped')

    def append(self,row):
        if self.closed:raise ValueError('record writer is closed')
        self._check()
        # Immutable IPC snapshots avoid deepcopy's large per-step object graph
        # and Queue's deferred traversal in the physics process. Pickle is only
        # private parent/child transport; on-disk records use the documented codec.
        self.rows.append(pickle.dumps(row,protocol=5))
        if len(self.rows)>=self.block_rows:self.flush()

    def flush(self):
        if self.rows:self._send(self.rows);self.rows=[]

    def close(self):
        if self.closed:return
        try:
            self.flush();self._send(None);self.process.join(timeout=30)
            if self.process.is_alive():
                self.process.terminate();self.process.join()
                raise RuntimeError('record worker did not drain within 30 seconds')
            if self.process.exitcode!=0:raise RuntimeError(f'record worker exited with code {self.process.exitcode}')
        finally:
            self.closed=True
            if self.process.is_alive():self.process.terminate();self.process.join()
            if self.process.exitcode!=0:self.blocks.cancel_join_thread();self.errors.cancel_join_thread()
            self.blocks.close();self.errors.close()
    def __enter__(self):return self
    def __exit__(self,*exc):self.close()


def open_writer(path,format=None,*,block_rows=128,background=False):
    format=format or DEFAULT_FORMAT
    if format=='binary':return (BackgroundBinaryWriter if background else BinaryWriter)(path,block_rows)
    if format=='jsonl':return JsonLinesWriter(path)
    raise ValueError(f'unknown record format {format!r}')


def write_row(writer,row):
    """Accept codec writers and legacy caller-owned text streams (StringIO etc.)."""
    if hasattr(writer,'append'):writer.append(row)
    else:writer.write(json.dumps(row,allow_nan=False)+'\n')


def record_path(directory,stem='record',format=None):
    return Path(directory)/(stem+('.xgpr' if (format or DEFAULT_FORMAT)=='binary' else '.jsonl'))


def find_record(directory,stem='record'):
    """Resolve new default paths, with old JSONL fallback. Explicit paths stay explicit."""
    directory=Path(directory)
    if directory.is_file():return directory
    for suffix in ('.xgpr','.jsonl'):
        candidate=directory/(stem+suffix)
        if candidate.exists():return candidate
    raise FileNotFoundError(f'no {stem} record in {directory}')


class _Cursor:
    def __init__(self,data):self.data=data;self.pos=0
    def take(self,n):
        end=self.pos+n
        if end>len(self.data):raise ValueError('completed block payload is malformed')
        value=self.data[self.pos:end];self.pos=end;return value
    def integer(self):return U32.unpack(self.take(4))[0]
    def variable(self):return self.take(self.integer())


def _decode(fields,data,count):
    cursor=_Cursor(data);rows=[{} for _ in range(count)]
    for field in fields:
        name=field['name'];mode=field['mode']
        if mode=='event':
            changes=[]
            for _ in range(cursor.integer()):
                index=cursor.integer();present=bool(cursor.take(1)[0]);value=cursor.variable()
                changes.append((index,present,json.loads(value) if present else None))
            if not changes or changes[0][0]!=0:raise ValueError('event column lacks block snapshot')
            change=0
            for index,row in enumerate(rows):
                while change+1<len(changes) and changes[change+1][0]<=index:change+=1
                _,present,value=changes[change]
                if present:row[name]=copy.deepcopy(value)
        elif mode=='fixed':
            packer=struct.Struct('<'+_codes(field['shape']))
            for row in rows:
                tag=cursor.take(1)[0]
                if tag==1:row[name]=_restore(field['shape'],iter(packer.unpack(cursor.take(packer.size))))
                elif tag==2:row[name]=json.loads(cursor.variable())
                elif tag!=0:raise ValueError('invalid fixed column tag')
        elif mode=='variable':
            for row in rows:
                present=cursor.take(1)[0]
                if present==1:row[name]=json.loads(cursor.variable())
                elif present!=0:raise ValueError('invalid variable column tag')
        else:raise ValueError(f'unknown column mode {mode}')
    for row in rows:row.update(json.loads(cursor.variable()))
    if cursor.pos!=len(data):raise ValueError('completed block has trailing payload')
    return rows


def _truncated(path,offset):
    warnings.warn(f'{path}: truncated/uncommitted record tail at byte {offset}; complete blocks recovered',
                  TruncatedRecordWarning,stacklevel=3)


def iter_records(path):
    """Yield original JSON-equivalent dicts; detect binary by magic, not suffix."""
    path=Path(path)
    if not path.exists() and path.suffix in ('.jsonl','.xgpr'):
        path=find_record(path.parent,path.stem)
    with path.open('rb') as file:
        magic=file.read(len(MAGIC))
        if magic!=MAGIC:
            file.seek(0)
            for line in file:
                yield json.loads(line)
            return
        raw=file.read(4)
        if len(raw)!=4:_truncated(path,file.tell());return
        length=U32.unpack(raw)[0];raw=file.read(length)
        if len(raw)!=length:_truncated(path,file.tell());return
        header=json.loads(raw)
        if header.get('schema_version')!=1:raise ValueError('unsupported binary record schema')
        if header.get('original_header') is not None:yield header['original_header']
        expected=0
        while True:
            offset=file.tell();marker=file.read(4)
            if marker==b'END1':return
            if not marker or len(marker)<4:_truncated(path,offset);return
            if marker!=b'BLK1':raise ValueError(f'bad block marker at byte {offset}')
            raw=file.read(BLOCK.size)
            if len(raw)!=BLOCK.size:_truncated(path,offset);return
            first,count,size,compressed_size=BLOCK.unpack(raw)
            compressed=file.read(compressed_size);commit=file.read(4)
            if len(compressed)!=compressed_size or len(commit)!=4:_truncated(path,offset);return
            if commit!=b'DONE':raise ValueError(f'bad block commit at byte {offset}')
            if first!=expected:raise ValueError('noncontiguous binary block rows')
            data=zlib.decompress(compressed)
            if len(data)!=size:raise ValueError('binary block length mismatch')
            yield from _decode(header['fields'],data,count)
            expected+=count


def read_header(path):
    rows=iter_records(path)
    try:return next(rows)
    finally:rows.close()


def block_index(path):
    """Scan committed block offsets without decompressing; no footer required."""
    with Path(path).open('rb') as file:
        if file.read(len(MAGIC))!=MAGIC:raise ValueError('block index requires binary record')
        raw=file.read(4)
        if len(raw)!=4:return
        file.seek(U32.unpack(raw)[0],1)
        while True:
            offset=file.tell();marker=file.read(4)
            if marker!=b'BLK1':return
            raw=file.read(BLOCK.size)
            if len(raw)!=BLOCK.size:return
            first,count,_,size=BLOCK.unpack(raw);file.seek(size,1)
            if file.read(4)!=b'DONE':return
            yield {'first_row':first,'rows':count,'offset':offset,'end_offset':file.tell()}

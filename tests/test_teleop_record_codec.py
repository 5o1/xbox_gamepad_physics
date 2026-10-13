"""Record structure, JSON/binary round trips and committed-block recovery."""
import copy
import math
from pathlib import Path
import tempfile
import unittest
import warnings
from teleop.record import (MAGIC,TruncatedRecordWarning,block_index,find_record,
                          iter_records,open_writer,record_path)


def strict_equal(test,a,b):
    test.assertIs(type(a),type(b))
    if isinstance(a,dict):
        test.assertEqual(set(a),set(b))
        for k in a:strict_equal(test,a[k],b[k])
    elif isinstance(a,list):
        test.assertEqual(len(a),len(b))
        for x,y in zip(a,b):strict_equal(test,x,y)
    else:
        test.assertEqual(a,b)
        if isinstance(a,float) and a==0:test.assertEqual(math.copysign(1,a),math.copysign(1,b))


class RecordCodecTest(unittest.TestCase):
    def rows(self):
        return [{'type':'header','schema_version':3,'config':{'label':'配置'}},
            {'type':'step','step':0,'target_pose':[1.,-0.,.12345678901234567],'command':{'opening':0,'fine':False},
             'state':'main','contacts':[],'input':{'seq':1,'received_ns':None},'frozen':{'pose':[1.,0.,0.]},'count':2},
            {'type':'step','step':1,'target_pose':[1.,0.,.12345678901234567],'command':{'opening':1.,'fine':True},
             'state':'secondary','contacts':[{'bodies':['指','pad'],'points':[{'impulse_ns':[.1,0.,0.]}]}],
             'input':{'seq':2,'received_ns':263705647542995},'frozen':{'pose':[1.,0.,0.]},'count':2},
            {'type':'step','step':2,'target_pose':[1.,0.,2.,3.],'command':{'opening':0,'fine':False},
             'contacts':[],'input':{},'frozen':None,'count':2.0,'new_field':{'mask':[True,0,1.]}},
            {'type':'step','step':3,'target_pose':[2.,0.,3.],'contacts':[],'input':{},'state':'main',
             'frozen':None,'count':False,'new_field':2**80}]

    def test_both_formats_roundtrip_types_shapes_events_extensions_and_sign_zero(self):
        rows=self.rows()
        with tempfile.TemporaryDirectory() as d:
            for format in ('jsonl','binary'):
                path=record_path(d,format=format)
                with open_writer(path,format,block_rows=2) as writer:
                    for r in rows:writer.append(r)
                actual=list(iter_records(path))
                strict_equal(self,rows,actual)
                self.assertEqual(find_record(d),path)

    def test_truncation_recovers_complete_blocks_and_warns(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'record.xgpr';rows=self.rows()
            with open_writer(path,'binary',block_rows=2) as writer:
                for r in rows:writer.append(r)
            blocks=list(block_index(path));self.assertEqual(len(blocks),2)
            data=path.read_bytes();cut=blocks[1]['offset']+(blocks[1]['end_offset']-blocks[1]['offset'])//2
            path.write_bytes(data[:cut])
            with warnings.catch_warnings(record=True) as notices:
                warnings.simplefilter('always');actual=list(iter_records(path))
            strict_equal(self,rows[:3],actual)
            self.assertTrue(any(issubclass(x.category,TruncatedRecordWarning) for x in notices))

    def test_magic_detection_and_legacy_jsonl_without_header(self):
        with tempfile.TemporaryDirectory() as d:
            for format in ('binary','jsonl'):
                path=Path(d)/('binary.jsonl' if format=='binary' else 'legacy.xgpr')
                rows=[{'step':0,'time':2.0},{'step':1,'time':3.0}]
                with open_writer(path,format) as writer:
                    for row in rows:writer.append(row)
                strict_equal(self,rows,list(iter_records(path)))

    def test_mutating_input_or_decoded_snapshot_does_not_change_other_rows(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'record.xgpr';row={'step':0,'frozen':{'pose':[1.,2.]}}
            with open_writer(path,'binary') as writer:
                writer.append(row);row['step']=1;row['frozen']['pose'][0]=3.;writer.append(row)
                row['step']=2;writer.append(row)
            actual=list(iter_records(path));self.assertEqual(actual[0]['frozen']['pose'][0],1.)
            actual[1]['frozen']['pose'][0]=9.;self.assertEqual(actual[2]['frozen']['pose'][0],3.)

    def test_clean_empty_and_header_only_and_missing_footer(self):
        with tempfile.TemporaryDirectory() as d:
            for rows in ([],[self.rows()[0]]):
                path=Path(d)/'record.xgpr'
                with open_writer(path,'binary') as writer:
                    for row in rows:writer.append(row)
                strict_equal(self,rows,list(iter_records(path)))
                path.write_bytes(path.read_bytes()[:-4])
                with self.assertWarns(TruncatedRecordWarning):strict_equal(self,rows,list(iter_records(path)))

    def test_background_writer_drains_and_preserves_the_same_rows(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'record.xgpr';rows=self.rows()
            with open_writer(path,'binary',block_rows=2,background=True) as writer:
                for row in rows:writer.append(row)
            strict_equal(self,rows,list(iter_records(path)))

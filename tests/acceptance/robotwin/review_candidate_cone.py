"""Replay saved cone traces through the production scorer without recollection."""
import argparse,json
from pathlib import Path
from .stick_cone_production import P,score_trace

def run(path,output=None):
 old=json.loads(path.read_text());protocol=json.loads(P.read_text());rows=[]
 for record in old['results']:
  trace_path=path.parent/(record['side']+'_'+record['direction'])/'trace.jsonl'
  trace=[json.loads(line) for line in trace_path.read_text().splitlines()]
  rows.append({'side':record['side'],**score_trace(record['direction'],trace,protocol),
               'old_runner_passed':record['passed'],'source_trace':str(trace_path.resolve())})
 result={'scope':'Same saved traces and unchanged written protocol; the live runner uses this same score_trace function. Historical raw results remain untouched.',
         'results':rows,'passed':all(row['passed'] for row in rows)}
 output=output or path.parent/'rescored_original_criteria.json'
 output.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result));return result['passed']

if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('results',type=Path);parser.add_argument('--output',type=Path)
 args=parser.parse_args();raise SystemExit(not run(args.results,args.output))

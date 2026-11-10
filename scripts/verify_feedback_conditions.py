"""Verify only two affected cases after Codex's source-based adjudication."""
import argparse, asyncio, json, os, sys, time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding='utf8')


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--runtime-pid',type=int,required=True)
    parser.add_argument('--output',required=True); args=parser.parse_args()
    import psutil
    os.environ.update({k:v for k,v in psutil.Process(args.runtime_pid).environ().items() if k.startswith('EDUMATRIX_')})
    from config import CONFIG
    from llm_client import AsyncOpenAIChatLLM
    from app.learning_feedback import generate_targeted_feedback, selected_strategy
    root=Path(args.output); out=root/'conditions-r195'; out.mkdir(exist_ok=True)
    cases=json.loads((root/'frozen-cases.json').read_text(encoding='utf8'))['cases']
    def save(path,value): path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf8')
    class Traced(AsyncOpenAIChatLLM):
        async def generate(self,system,user,**kwargs):
            start=time.monotonic(); record={'system':system,'input':json.loads(user),'role':kwargs.get('role')}
            path=out/f'call-{time.time_ns()}.json'
            try:
                raw=await super().generate(system,user,**kwargs)
                record.update(status='completed',output=raw); return raw
            except Exception as exc:
                record.update(status='failed',error_type=type(exc).__name__); raise
            finally:
                record['seconds']=round(time.monotonic()-start,3); save(path,record)
    backend=Traced(CONFIG.llm_endpoint,CONFIG.llm_api_key,model='deepseek-v4-flash',temperature=0,
        max_tokens=16384,timeout_seconds=CONFIG.llm_timeout,thinking_mode='enabled',reasoning_effort='medium')
    async def one(case):
        path=out/(case['id']+'.json')
        if path.exists(): return
        output=await generate_targeted_feedback(backend,case['context'])
        save(path,{'input':case['context'],'output':output,'policy':selected_strategy(),
            'revision':'shared model-evaluation conditions r195','not_reoptimized':True})
        print(case['id'],'completed',flush=True)
    async def run():
        results=await asyncio.gather(*(one(c) for c in cases if c['id'] in ('val-training','heldout-fold')),return_exceptions=True)
        for result in results:
            if isinstance(result,Exception): raise result
    asyncio.run(run())


if __name__=='__main__': main()

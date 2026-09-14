from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from famou.benchmark_comparison import (
 BenchmarkComparisonError,
 BenchmarkComparisonPlan,
 admit_benchmark_comparison_plan,
 parse_benchmark_comparison_plan,
)
from famou.benchmark_task import BenchmarkTaskEnvelope


def env(benchmark='sky'):
 b=b'{"items":[1]}'
 return BenchmarkTaskEnvelope.from_dict({'schema_version':'1','protocol':'lunar-benchmark-task-v1','benchmark':{'name':benchmark,'release_version':'v','publication_digest':'sha256:'+'a'*64},'task':{'key':'t','revision_id':'r','digest':'sha256:'+'b'*64,'entrypoint':'task.json'},'contract_sha256':'c'*64,'inputs':[{'path':'task.json','size':len(b),'sha256':hashlib.sha256(b).hexdigest()}],'model':{'requested':'m','profile_sha256':'d'*64},'evaluator':{'kind':'exact_harness','extractor_sha256':'a'*64,'evaluator_sha256':'b'*64},'candidate':{'kind':'single_file','filename':'candidate.py'},'budget':{'attempts':2,'timeout_seconds':30.0,'max_total_tokens':1000,'max_cost_micros':5000}})

def test_roundtrip_and_common_identity(tmp_path: Path):
 (tmp_path/'task.json').write_bytes(b'{"items":[1]}')
 plan=BenchmarkComparisonPlan.from_envelopes({'sky':env(), 'llm4ad':env('llm4ad')})
 assert BenchmarkComparisonPlan.from_dict(plan.to_dict()).digest()==plan.digest()
 out=admit_benchmark_comparison_plan(plan,contract_sha256='c'*64,input_root=tmp_path,model_profile_sha256='d'*64,evaluator_fingerprint='b'*64)
 assert out.comparison_id==plan.comparison_id and len(out.arms)==2

def test_rejects_arm_identity_drift(tmp_path: Path):
 (tmp_path/'task.json').write_bytes(b'{"items":[1]}')
 first=env(); second=env('llm4ad'); second=BenchmarkTaskEnvelope.from_dict({**second.to_dict(),'candidate':{'kind':'single_file','filename':'other.py'}})
 plan=BenchmarkComparisonPlan.from_envelopes({'sky':first,'llm4ad':second})
 with pytest.raises(BenchmarkComparisonError): admit_benchmark_comparison_plan(plan,contract_sha256='c'*64,input_root=tmp_path,model_profile_sha256='d'*64,evaluator_fingerprint='b'*64)

def test_parser_rejects_duplicate_keys(tmp_path: Path):
 p=tmp_path/'plan.json'; p.write_text('{"schema_version":"1","schema_version":"1"}')
 with pytest.raises(BenchmarkComparisonError): parse_benchmark_comparison_plan(p)

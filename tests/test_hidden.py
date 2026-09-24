import base64
import json
import tempfile
import unittest
from pathlib import Path
from fixlab.core import Workspace
from fixlab.evaluation import snapshot, acceptance, run_evaluated


class HiddenTests(unittest.TestCase):
    def test_partial_fix_passes_public_but_fails_hidden(self):
        root = Path('benchmarks_advanced/pagination')
        before = snapshot(root/'repo')
        hidden = snapshot(root/'hidden')
        after = dict(before)
        after['paging.py'] = base64.b64encode(b'def bounds(page,size):\n    return (page-1)*size,page*size\n').decode()
        self.assertTrue(acceptance(before, after)['passed'])
        result = acceptance(before, after, hidden=hidden)
        self.assertFalse(result['passed'])
        self.assertGreater(result['failures'] + result['errors'], 0)

    def test_hidden_not_in_model_workspace_or_messages_and_resume_preserves_it(self):
        hidden = snapshot(Path('benchmarks_advanced/pagination/hidden'))
        files = snapshot(Path('benchmarks_advanced/pagination/repo'))
        class Model:
            def reply(inner, messages):
                self.assertNotIn('test_hidden_cases', json.dumps(messages))
                self.assertFalse(list(repo.glob('test_hidden*')))
                return {'role':'assistant','content':'done'}, {}
        with tempfile.TemporaryDirectory() as temp:
            repo=Path(temp)/'repo'; repo.mkdir()
            for name,content in files.items():
                (repo/name).write_bytes(base64.b64decode(content))
            state=Path(temp)/'state.sqlite'
            report=run_evaluated(Workspace(repo),Model(),'fix',state,hidden=hidden)
            resumed=run_evaluated(Workspace(repo),Model(),'fix',state)
            self.assertTrue(report['has_hidden_tests'])
            self.assertTrue(resumed['has_hidden_tests'])
            self.assertEqual(report['acceptance']['tests_run'], resumed['acceptance']['tests_run'])
            with self.assertRaisesRegex(ValueError,'Hidden tests changed'):
                run_evaluated(Workspace(repo),Model(),'fix',state,hidden={})

    def test_advanced_fixtures_and_reference_fixes(self):
        fixes = {
            'pagination': {'paging.py': 'def bounds(page,size):\n    if type(page) is not int or type(size) is not int or page<1 or size<1: raise ValueError()\n    return (page-1)*size,page*size\n'},
            'inventory': {'orders.py': 'def fulfill(stock,lines):\n    requested={}\n    for sku,qty in lines:\n        if type(qty) is not int or qty<=0: raise ValueError()\n        requested[sku]=requested.get(sku,0)+qty\n    for sku,qty in requested.items():\n        if sku not in stock or stock[sku]<qty: raise ValueError()\n    for sku,qty in requested.items(): stock[sku]-=qty\n    return sum(requested.values())\n'},
            'money': {'money.py':'from decimal import Decimal,InvalidOperation\ndef parse(value):\n    try: result=Decimal(value)\n    except (InvalidOperation,ValueError,TypeError): raise ValueError()\n    if not result.is_finite() or result<0: raise ValueError()\n    return result\n', 'checkout.py':'from decimal import Decimal,ROUND_HALF_UP\nfrom money import parse\ndef total(prices,discount):\n    rate=parse(discount)\n    if rate>1: raise ValueError()\n    value=sum((parse(p) for p in prices),Decimal(0))*(1-rate)\n    return format(value.quantize(Decimal("0.01"),rounding=ROUND_HALF_UP),".2f")\n'}
        }
        for name, replacements in fixes.items():
            with self.subTest(task=name):
                root=Path('benchmarks_advanced')/name
                before=snapshot(root/'repo'); hidden=snapshot(root/'hidden')
                initial=acceptance(before,before,hidden=hidden)
                self.assertFalse(initial['passed'])
                self.assertGreater(initial['tests_run'],1)
                after={**before,**{k:base64.b64encode(v.encode()).decode() for k,v in replacements.items()}}
                final=acceptance(before,after,hidden=hidden)
                self.assertTrue(final['passed'],final['output'])

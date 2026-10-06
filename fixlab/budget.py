"""Cumulative, cooperative task budgets and user-priced cost estimates."""
import math
import time


class BudgetExceeded(Exception):
    def __init__(self, reason):
        self.reason = reason
        super().__init__(reason)


def validate(options):
    options = dict(options or {})
    allowed = {'max_tokens', 'max_seconds', 'input_price', 'output_price', 'currency'}
    if options.keys() - allowed:
        raise ValueError('Unknown budget option')
    for key in ('max_tokens', 'max_seconds', 'input_price', 'output_price'):
        value = options.get(key)
        if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(value) or value < 0 or (key.startswith('max_') and value == 0)):
            raise ValueError(key + ' must be finite and ' + ('positive' if key.startswith('max_') else 'nonnegative'))
    if options.get('max_tokens') is not None and not isinstance(options['max_tokens'], int):
        raise ValueError('max_tokens must be an integer')
    if (options.get('input_price') is None) != (options.get('output_price') is None):
        raise ValueError('Provide both input and output prices per million tokens')
    if options.get('input_price') is not None and not str(options.get('currency', '')).strip():
        raise ValueError('Provide currency with prices')
    return options


def accounting(events, options):
    usage = [p for k, p in events if k == 'usage']
    complete = bool(usage) and all(isinstance(p.get('total_tokens'), (int, float)) for p in usage)
    complete = complete and not any(k == 'api_retry' for k, p in events)
    total = sum(p.get('total_tokens') or 0 for p in usage)
    cost = None
    if options.get('input_price') is not None:
        priced = all(p.get('prompt_tokens') is not None and p.get('completion_tokens') is not None for p in usage)
        amount = sum((p.get('prompt_tokens') or 0) * options['input_price'] +
                     (p.get('completion_tokens') or 0) * options['output_price'] for p in usage) / 1_000_000
        cost = {'estimated_amount': amount, 'currency': options['currency'],
                'complete': complete and priced, 'input_price_per_million': options['input_price'],
                'output_price_per_million': options['output_price']}
    return {'used_tokens': total, 'token_usage_complete': complete, 'cost': cost}


class Budget:
    def __init__(self, store, options):
        self.store = store
        self.options = validate(options)
        self.start = time.monotonic()
        self.previous_seconds = sum(p for k, p in store.events() if k == 'execution_seconds')

    def check(self):
        events = self.store.events()
        limit = self.options.get('max_seconds')
        if limit is not None and self.previous_seconds + time.monotonic() - self.start >= limit:
            raise BudgetExceeded('max_seconds')
        limit = self.options.get('max_tokens')
        if limit is not None:
            usage = [p for k, p in events if k == 'usage']
            if any(p.get('total_tokens') is None for p in usage) or any(k == 'api_retry' for k, p in events):
                raise BudgetExceeded('token_usage_unknown')
            if sum(p.get('total_tokens') or 0 for p in usage) >= limit:
                raise BudgetExceeded('max_tokens')

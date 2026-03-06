# Ruby→Python Conversion Evaluation

**Date:** 2026-03-06
**Proxy:** http://localhost:8000/v1/chat/completions
**Model:** meta/llama-3.1-70b-instruct (via NVIDIA free tier)
**Auth:** TokenBroker key `tkb_test_123`

## Results

| File | Tokens | Time (s) | Status | Notes |
|------|--------|----------|--------|-------|
| hello.rb | 146 | 1.20 | OK | Correct class + f-string |
| calculator.rb | 364 | 2.96 | OK | history list, all methods correct |
| user.rb | 307 | 2.27 | OK | @classmethod, @property, __str__ |
| **Total** | **817** | **6.43** | **3/3** | |

## Quality Assessment

**hello.rb → hello.py** ✅
- Ruby `puts` → `print()` correct
- Ruby string interpolation `#{@name}` → Python f-string `{self.name}` correct

**calculator.rb → calculator.py** ✅
- `@history` (instance var) → `self.history` correct
- `.inspect` (Ruby) → `.get_history()` (sensible rename)
- All arithmetic methods preserved

**user.rb → user.py** ✅
- `attr_accessor` → standard `self.x` attributes correct
- `adult?` (Ruby predicate) → `@property adult` (Pythonic)
- `self.create` (Ruby class method) → `@classmethod` correct
- `to_s` → `__str__` correct

## Conclusion

- **Conversion quality: Excellent** – model uses idiomatic Python patterns
- **Cost: 817 tokens total** = ~$0.00011 at DeepSeek prices (or free via NVIDIA)
- **Speed: ~2s per file** via NVIDIA free tier
- TokenBroker proxy adds <50ms overhead

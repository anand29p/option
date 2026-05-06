from itertools import combinations

base = ['RSIDivergence', 'VWAPReversion', 'ORBBreakout', 'MeanReversion']

combos_2 = list(combinations(base, 2))
combos_3 = list(combinations(base, 3))

print(f'\n✅ 2-SIGNAL PAIRS ({len(combos_2)} combinations):')
for i, combo in enumerate(combos_2, 1):
    print(f'   {i}. {" + ".join(combo)}')

print(f'\n✅ 3-SIGNAL TRIPLETS ({len(combos_3)} combinations):')
for i, combo in enumerate(combos_3, 1):
    print(f'   {i}. {" + ".join(combo)}')

print(f'\n✅ 4-SIGNAL CONSENSUS (all strategies must agree):')
print(f'   1. RSIDivergence + VWAPReversion + ORBBreakout + MeanReversion')

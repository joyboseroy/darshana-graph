import json
data = json.load(open('corpus/brahma_sutras_nimbarka.json'))
for r in data:
    print(r['segment_id'])
    if r['commentaries']:
        print('Nimbarka:', r['commentaries'][0]['text'][:150])
        print('Srinivasa:', r['commentaries'][1]['text'][:150])
    else:
        print('NO COMMENTARIES CAPTURED')
    print()

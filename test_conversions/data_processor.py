class DataProcessor:
    def __init__(self, records):
        self.records = records

    def summary(self):
        return {
            'total': len(self.records),
            'average': self.average_value(),
            'max': max(r['value'] for r in self.records),
            'min': min(r['value'] for r in self.records),
        }

    def filter_by_category(self, category):
        return [r for r in self.records if r['category'] == category]

    def group_by_category(self):
        return {k: list(g) for k, g in self._group_by(self.records, 'category')}

    def top_n(self, n):
        return sorted(self.records, key=lambda r: r['value'], reverse=True)[:n]

    def transform(self):
        return [
            {
                'id': r['id'],
                'label': r['name'].upper(),
                'score': round(r['value'] * 1.1, 2),
                'category': r['category'],
            }
            for r in self.records
        ]

    def total_by_category(self):
        return {k: sum(r['value'] for r in v) for k, v in self.group_by_category().items()}

    def average_value(self):
        if not self.records:
            return 0.0
        return round(sum(r['value'] for r in self.records) / len(self.records), 2)

    @staticmethod
    def _group_by(data, key):
        result = {}
        for item in data:
            k = item[key]
            if k not in result:
                result[k] = []
            result[k].append(item)
        return result.items()


records = [
    {'id': 1, 'name': 'alpha', 'value': 42, 'category': 'A'},
    {'id': 2, 'name': 'beta', 'value': 17, 'category': 'B'},
    {'id': 3, 'name': 'gamma', 'value': 95, 'category': 'A'},
    {'id': 4, 'name': 'delta', 'value': 63, 'category': 'B'},
    {'id': 5, 'name': 'epsilon', 'value': 28, 'category': 'A'},
]

dp = DataProcessor(records)
print(dp.summary())
print([r['name'] for r in dp.filter_by_category('A')])
print([r['name'] for r in dp.top_n(3)])
print(dp.total_by_category())
print(dp.transform()[0])

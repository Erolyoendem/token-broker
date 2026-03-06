def word_count(text):
    counts = {}
    for w in text.lower().split():
        counts[w] = counts.get(w, 0) + 1
    return counts

text = "the quick brown fox jumps over the lazy dog the fox"
for word, count in sorted(word_count(text).items(), key=lambda x: x[1], reverse=True)[:5]:
    print(f"{word}: {count}")

class FormalGreeter:
    TITLES = {"en": "Mr.", "de": "Herr", "fr": "M."}

    def __init__(self, lang="en"):
        self.lang = lang

    def greet(self, name):
        title = self.TITLES.get(self.lang, "")
        print(f"Hello, {title} {name}!")

for lang in ["en", "de", "fr"]:
    FormalGreeter(lang).greet("Smith")

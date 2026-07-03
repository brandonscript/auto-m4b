ENABLED = False


class ImportDebug:
    IMPORTS: list[tuple[int, str]] = []

    def push(self, filename: str):
        # looks through imports and adds the import to the list, where the first element is the filename, and the second incrememnts the previous filename's count by 1. If not found, it adds the import to the list with a count of 0.

        if not ENABLED:
            return
        print(" " * (len(self.IMPORTS) * 2) + " → " + filename)
        self.IMPORTS.append((len(self.IMPORTS) * 2, filename))

    def pop(self, filename: str):
        if not ENABLED:
            return
        # find most recently added matching filename and remove it from the list
        for i, (indent, name) in enumerate(reversed(self.IMPORTS)):
            if name == filename:
                print(" " * indent + " ← " + filename)
                self.IMPORTS.pop(len(self.IMPORTS) - i - 1)
                break


bug = ImportDebug()

import itertools


class LazyLoadingList(object):
    """a lazy-loading and trasparently-caching list type

    accepts an iterable (probably a generator) and caches as it iterates

    supports:
        __iter__ (evaluates the full generator),
        __getitem__ (no slices, evaluates up to the requested index),
        __setitem__ (no slices, evaluates up to the requested index),
        __delitem__ (no slices, evaluates up to the requested index),
        __len__ (evaluates the full generator),
        pop (evaluates up to the index, or the full generator),
        append (no evaluation),
        extend (no evaluation),
        sort (evaluates the full generator)
    """

    def __init__(self, gen, prefix=None, postfix=None):
        self._gen = gen
        self._prefix = []
        self._postfix = []
        self._complete = False

    def _yield_from_gen(self):
        if self._complete:
            return

        for item in self._gen:
            self._prefix.append(item)
            yield item

        self._complete = True

    def _get_to(self, index):
        if self._complete:
            return

        if len(self._prefix) > index:
            return

        gen = self._yield_from_gen()
        while len(self._prefix) - 1 < index:
            gen.next() # let the StopIteration through

    def __iter__(self):
        return itertools.chain(self._prefix, self._yield_from_gen(),
                               self._postfix)

    def __getitem__(self, index):
        if not isinstance(index, (int, long)):
            raise TypeError("integer index required")

        loaded = len(self._prefix)
        if index < loaded:
            return self._prefix[index]

        gen = self._yield_from_gen()
        for i in xrange(index - loaded + 1):
            try:
                self._get_to(index)
                return self._prefix[index]
            except StopIteration:
                loaded = len(self._prefix)
                if len(self._postfix) > index - loaded:
                    return self._postfix[index - loaded]
                raise IndexError("index out of range")

    def __setitem__(self, index, item):
        if not isinstance(index, (int, long)):
            raise TypeError("integer index required")

        if index < len(self._prefix):
            self._prefix[index] = item
            return

        try:
            self._get_to(index)
            self._prefix[index] = item
        except StopIteration:
            self._postfix[index - len(self._prefix)] = item

    def __delitem__(self, index):
        if not isinstance(index, (int, long)):
            raise TypeError("integer index required")

        if index < len(self._prefix):
            del self._prefix[index]
            return

        try:
            self._get_to(index)
            del self._prefix[index]
        except StopIteration:
            del self._postfix[index - len(self_prefix)]

    def __len__(self):
        tuple(self._yield_from_gen())
        return len(self._prefix) + len(self._postfix)

    def __repr__(self):
        return "[%s]" % ", ".join(map(repr, self))

    __unicode__ = __str__ = __repr__

    def pop(self, index=None):
        if index is None:
            if self._postfix:
                return self._postfix.pop()
            tuple(self._yield_from_gen())
            return self._prefix.pop()

        if not isinstance(index, (int, long)):
            raise TypeError("integer index required")

        try:
            self._get_to(index)
        except StopIteration:
            pass
        item = self[index] # let the IndexError through
        del self[index]
        return index

    def append(self, item):
        self._postfix.append(item)

    def extend(self, gen):
        if self._complete:
            if self._postfix:
                self._gen = itertools.chain(gen, self._postfix)
                self._postfix = []
            else:
                self._gen = gen
        else:
            if self._postfix:
                self._gen = itertools.chain(self._gen, gen, self._postfix)
                self._postfix = []
            else:
                self._gen = itertools.chain(self._gen, gen)
        self._complete = False

    def sort(self, *args, **kwargs):
        self._prefix.extend(self._yield_from_gen())
        self._prefix.extend(self._postfix)
        self._postfix[:] = []
        self._prefix.sort(*args, **kwargs)

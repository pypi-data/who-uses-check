# A stand-in package for the end-to-end test: a pull request that removes `moves` should get a
# comment listing the PyPI packages that use six.moves.
moves = None


def b(s):
    return s.encode("latin-1")

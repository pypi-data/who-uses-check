# py-code who-uses check

A GitHub Action for Python library maintainers. When a pull request removes or renames a public
function, class, method or module, it looks the old name up in the
[py-code.org](https://py-code.org) index and comments with the PyPI packages that use it.

The index covers the latest release of more than 335,000 PyPI projects and records every name
their code imports or reaches by attribute, with the file and line.

Example comment, for urllib3 1.26 → 2.0:

> ### Public names removed in this change
>
> 111 public names removed or renamed (343 counting class members). 11 of them are used by packages on PyPI.
>
> | Removed name | PyPI packages using it | Most downloaded users |
> |---|--:|---|
> | `urllib3.util.ssl_.DEFAULT_CIPHERS` | 11 | botocore (804.5M/mo), awscli (78.5M/mo), ibm-cos-sdk-core (1.2M/mo), … |
> | `urllib3.request.RequestMethods` | 8 | google-auth (329.7M/mo), apache-skywalking (4.1K/mo), … |
> | `urllib3.contrib.appengine` | 6 | cloudinary (1.5M/mo), clearml (357.2K/mo), … |
> | `urllib3.response.HTTPResponse.from_httplib` | 6 | oci (1.7M/mo), ytsaurus-client (385.0K/mo), … |

## Usage

```yaml
# .github/workflows/who-uses.yml
name: who uses removed names
on: pull_request

permissions:
  contents: read
  pull-requests: write   # to comment

jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5
      - uses: pypi-data/who-uses-check@v1
```

The action finds the packages in `src/` or the repository root, compares the base and the head of
the pull request, and posts one comment that it updates on each push. It posts nothing when no
public name was removed. The same report goes to the job summary, so it is still visible on pull
requests from forks, where the token cannot comment.

## Inputs

| Input | Default | Meaning |
|---|---|---|
| `source` | `src/` if it holds a package, else the root | Folder that holds the package |
| `packages` | every package in `source` | Comma-separated top-level packages to check |
| `base` | the pull request's base commit | Commit to compare against |
| `min-downloads` | `0` | Only count users with at least this many downloads in 30 days |
| `max-lookups` | `300` | Look up at most this many removed names |
| `comment` | `true` | Comment on the pull request |
| `fail-on-used` | `false` | Fail the check when a removed name is used on PyPI |
| `client` | `py-code-org>=0.1,<1` | pip requirement for the lookup client |

Outputs: `removed` (names removed, with a removed class or module counted once) and `used`
(how many of them packages on PyPI use).

## What counts as public

The action parses both versions with `ast`; it does not import your code.

- Modules whose name starts with `_` are private, and so is everything in them.
- If a module has a literal `__all__`, its public names are the ones listed.
- Otherwise every top-level function, class, variable and in-package re-export without a leading
  `_` is public, including those under top-level `if`, `try` and `with` blocks.
- Methods and class attributes of public classes are public, including inherited ones, and so are
  the members of a class re-exported under another path.
- `tests`, `docs` and `examples` folders are skipped.

Names are compared as users write them, such as `pkg.Client.send` and `pkg.client.Client.send`,
so moving a class but keeping the old import path working is not reported.

## Limits

- The index has the latest release of each project only, and misses dynamic imports
  (`importlib.import_module`, `getattr`) and names reached through variables.
- Signature changes, such as a removed parameter, are not detected.
- The lookup sends only the removed names to `data.py-code.org`, which serves static JSON files.

## Licence

MIT. The index and the `py-code-org` client are at
[pypi-data/py-code](https://github.com/pypi-data/py-code).

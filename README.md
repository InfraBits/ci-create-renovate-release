# Create renovate release

Create an incremental GitHub release on renovate changes.

## Example Usage

```
  create-renovate-release:
    runs-on: ubuntu-latest
    steps:
      - uses: infrabits/ci-create-renovate-release@main
        with:
          github_token: ${{ secrets.GITHUB_TOKEN }}
```

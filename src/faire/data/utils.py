import bids.layout
import datalad.api as dlad
from datalad.runner.exception import CommandError
from typing import Dict

BIDS_MERGE_SEARCH_MAX_DEPTH = 10

def commit2entities(ds:dlad.Dataset) -> Dict:
    for ci in range(1, BIDS_MERGE_SEARCH_MAX_DEPTH):
        try:
            for l in ds.repo.call_git_items_(['diff', '--name-only',f'HEAD~{ci}']):
                if 'sub' in l:
                    return bids.layout.parse_file_entities(l)
        except CommandError:
            break
    raise RuntimeError('cannot determine entities of the new sample of data')

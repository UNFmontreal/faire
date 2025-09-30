import os
import typer
import pathlib
import logging
from datalad import api as dlad
from datalad_container.containers_run import ContainersRun
from datalad_container.find_container import find_container_
from typing import Optional, Any, Dict, List
from ..git_hosts import DEFAULT_GITHOST
from ..data.utils import commit2entities

app = typer.Typer()

DATASET_BRANCH = os.environ.get("CI_COMMIT_BRANCH", "dev")
TRIGGER_SOURCEDATA = os.environ.get("FAIRE_TRIGGER_SOURCEDATA")
TRIGGER_SOURCEDATA_BRANCH = os.environ.get("FAIRE_TRIGGER_SOURCEDATA_BRANCH")

lgr = logging.getLogger('faire.cli.run')

@app.command()
def run(
    container_name:Optional[str]=None,
    push_data_remotes: List[str]=[],
    push: bool = True,
) -> None:
    """
    Run the configured pipeline on newly added session or on the full dataset
    """
    from .main import ds
    # 2 usecases:
    # - run the pipeline on a new session (sourcedata updated, with commit containing new sample (eg. subject/session))
    # - run on all subjects (repo get created with sourcedata already containing a bunch of data)

    # get the sourcedata sub-datasets (try reckless ephemeral for containers and maybe raw data if ria-store storage)
    ds.get(recursive=True, recursion_limit=1, get_data=False)
    # checkout sourcedata to wanted branch (passed from env-var or dev/pilot branch)
    for subds_info in ds.subdatasets(return_type='list'):
        subds = dlad.Dataset(subds_info['path'])
        if not 'sourcedata' in subds_info['gitmodule_path']:
            continue
        subds.repo.checkout(TRIGGER_SOURCEDATA_BRANCH if subds_info['gitmodule_path'] == TRIGGER_SOURCEDATA else DATASET_BRANCH)
    ds.save("checkout subdatasets branches")

    # extract entities for new sample
    trigger_sdata = dlad.Dataset(ds.subdatasets(TRIGGER_SOURCEDATA, return_type='item-or-list')['path'])
    new_sample_entities = commit2entities(trigger_sdata)

    new_sample_name = "sub-{subject}_ses-{session}".format(**new_sample_entities)

    container = get_container(ds, TRIGGER_SOURCEDATA, container_name)
    if container is None:
        raise RuntimeError("couldn't find the requested container")

    # branch current derivative from base
    new_branch_name = f"{container["name"]}/{new_sample_name}"
    ds.repo.checkout(new_branch_name, ['-B'])
    ds.save(path='.', message='set sourcedata')
    # run the appropriate container:
    # if only one: easy
    # if multiple containers: config datalad.containers.<container_name>.sourcedata could serve to decide pipeline depending on which submodule is updated
    # eg. for BIDS: dicoms -> heudiconv, mrs -> spec2nii, physio -> phys2bids, eyetracking -> pupil2bids


    # check required inputs presents for the current sample (eg sequences in MRI sessions), otherwise exit without errors but explicit warning
    inputs_list = check_inputs_present(ds, container)

    cmd = container['cmd'].format(
        sourcedata=TRIGGER_SOURCEDATA,
        **new_sample_entities,
    )

    ds.containers_run(
        cmd,
        container_name=container_name,
        inputs=inputs_list,
        outputs=container.get('outputs',None),
    )

    if not push:
        return

    # push data
    for remote in push_data_remotes:
        lgr.info(f"pushing to {remote}")
        ds.push(to=remote)

    ## if CI/DATA remotes configured
    if DEFAULT_GITHOST:
        # push git
        for remote in push_git_remotes:
            ds.push(to=remote)

        container["artifact_paths"]

        description = ""
        if container.get("report_paths"):
            report_paths = list(ds.root.glob(container["report_paths"]))
            if len(report_paths):
                description += "reports:"
                for report_path in report_paths:
                    report_path.basename
                    description += f"\n- [{report_path.stem}]({DEFAULT_GITHOST.job_artifact_path}/{report_path})"

        # open PR
        DEFAULT_GITHOST.open_pr(
            repo_path=DEFAULT_GITHOST.repo_path,
            source_branch=new_branch_name,
            target_branch=target_branch,
            title=f"run {container_name} on {new_sample_name}",
            description=description,
        )


def get_container(ds:dlad.Dataset, trigger_sourcedata:str=None, container_name: str=None) -> List[Dict]:

    sourcedata2container = {
        v:k.split('.')[2] for k,v in  ds.config.items() if 'datalad.containers.' in k and '.sourcedata' in k
    }

    for res in find_container_(ds, container_name):
        if res.get("action") == "containers":
            return res

def check_inputs_present(ds:dlad.Dataset, container:Dict[str, Any]) -> Optional[List[str]]:
    """
    Check that required inputs required by the pipeline are present in the sample
    Return the list of inputs (required and optional that are present)
    """
    req_inputs = container.get('inputs-required', "").split(':')
    opt_inputs = container.get('inputs-optional', "").split(':')

    all_inputs = req_inputs
    for req_input in req_inputs:
        if not ds.root.glob(req_input):
            return
    for opt_input in opt_inputs:
        if ds.root.glob(opt_input):
            all_inputs.append(opt_input)
    return all_inputs

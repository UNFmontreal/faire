import pathlib
from enum import Enum
from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, Dict, Enum

class ProcessReport(BaseModel):
	report_pattern: str
	asset_patterns: list[str]

class StorageRemote(BaseModel):
	suffix: str
	wanted: str

class DataSource(BaseModel):
	url: pathlib.Path
	required_paths: list[str]
	parameters: Optional[list[str]] = None

class ProcessStage(str, Enum):
	merge = "merge"
	review = "review"

class Process(BaseModel):

	# list the sources that are required to execute that process
	sources: Dict[pathlib.Path, DataSource]
	# should that process run when sourcedata sample if merged or staged (PR)
	stage: ProcessStage = "merge"

	report: Optional[ProcessReport] = None
	review: Optional[bool] = Field(
		default = True,
		description = "wether this process results needs to be reviewed"
	)
	invoked_after: Optional[str] = Field(
		default_value = None,
		description = "name of another process that needs to be ran before that one, on the same branch"
	)


class StudyDataset(BaseModel):

	NAME: str
	TEMPLATE_URL: Optional[str] = None

	processes: Dict[str, Process] = Field(
			description = "list of processed that generate/modify content in that dataset"
	)
	remotes: Optional[list[StorageRemote]] = Field(
		default_factory = lambda data: [StorageRemote(suffix=f".{data['NAME']}", wanted="include=*")],
		description = "list of remotes where that dataset stores data"
	)

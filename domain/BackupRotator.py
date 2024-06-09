#!/usr/bin/env python3

"""

Mike's Backup Rotator

A simple script to help automatically rotate backup files

Copyright 2024 Mike Peralta; All rights reserved

Releasing to the public under the GNU GENERAL PUBLIC LICENSE v3 (See LICENSE file for more)

"""


from domain.config.Config import Config
from domain.config.ConfigFile import ConfigFile
from domain.Logger import Logger
from domain.Util import Util


import datetime
from pathlib import Path
import shutil


class BackupRotator:
	
	def __init__(
			self,
			config_paths: [Path] = None,
			debug: bool = False,
			systemd: bool = False,
			write_to_syslog: bool = False
	):
		self.__logger = Logger(
			name=type(self).__name__,
			debug=debug,
			systemd=systemd,
			write_to_syslog=write_to_syslog,
		)
		
		self.__config = Config(
			logger=self.__logger,
			config_files_paths=config_paths
		)
		
		self.__global_dry_run = True
		self.__calculated_actions = []
	
	def run(self, global_dry_run: bool = True):
		
		self.info("Begin rotating")
		
		self.__global_dry_run = global_dry_run
		if self.__global_dry_run:
			self.info(f"Running as a dry run, globally.")
		else:
			self.info(f"Won't run as a global dry run.")
		
		# Rotate once per config
		config_file_index = -1
		for config_file in self.__config.config_files:
			
			config_file: ConfigFile
			config_file_index += 1
			
			self.info(
				f"Rotating for config {config_file_index + 1} of {len(self.__config.config_files)}"
				f" : {config_file.path}"
				f"\n{config_file}"
			)
			self._do_rotate(config_file)
	
	@staticmethod
	def current_time():
		
		now = datetime.datetime.now()
		now_s = now.strftime("%b-%d-%Y %I:%M%p")
		return str(now_s)
	
	def debug(self, s):
		self.__logger.debug(s)
	
	def info(self, s):
		self.__logger.info(s)
	
	def warn(self, s):
		self.__logger.warning(s)
	
	def error(self, s):
		self.__logger.error(s)
	
	def _do_rotate(self, config: ConfigFile):
		
		self.info(
			f"Rotating for config: {config.path}"
		)
		if config.dry_run:
			self.info(
				f"Config {config.path.name} is set for a dry run (no deleting)."
			)
		else:
			self.info(
				f"Config {config.path.name} is not set for a dry run (will delete)."
			)
		
		self._rotate_paths(config=config)
	
	def _rotate_paths(self, config: ConfigFile):
		
		paths = config.rotatable_paths
		self.info(f"Begin rotating {len(paths)} paths")
		
		for path in paths:
			
			path: Path
			
			self._rotate_path(config=config, path=path)
	
	def _rotate_path(self, config: ConfigFile, path: Path):
		
		assert path.is_dir(), (
			f"Path should be a directory: {path}"
		)
		
		self.info(
			f"Rotating path: {path}"
		)
		
		self._rotate_path_for_maximum_items(
			config=config,
			path=path,
		)
		
		self._rotate_path_for_maximum_age(
			config=config,
			path=path,
		)
	
	def _rotate_path_for_maximum_items(self, config: ConfigFile, path: Path):
		
		assert path.is_dir(), f"Path should be a directory: {path}"
		
		if config.maximum_items:
			self.info(
				f"Rotating path for a maximum of {config.maximum_items} items: {path}"
			)
		else:
			self.info(
				f"Not configured to rotate for maximum number of items."
			)
			return
		
		candidate_items = self._gather_rotation_candidates(config=config, path=path)
		
		minimum_items = self._determine_minimum_items(config=config)
		
		# Do we need to rotate anything out?
		if len(candidate_items) < minimum_items:
			
			self.info(
				f"Path only has {len(candidate_items)} items"
				f", which does not meet the minimum threshold of {minimum_items} items."
				" Won't rotate this path."
			)
			return
		
		elif len(candidate_items) <= config.maximum_items:
			self.info(
				f"Path only has {len(candidate_items)} items"
				f", but needs more than {config.maximum_items} for rotation"
				"; Won't rotate this path."
			)
			return
		
		self.info(f"Found {len(candidate_items)} items to examine")
		
		#
		maximum_purge_count = len(candidate_items) - minimum_items
		purge_count = len(candidate_items) - config.maximum_items
		self.info(f"Want to purge {purge_count} items")
		
		if purge_count > maximum_purge_count:
			self.info(
				f"Reducing purge count from"
				f" {purge_count} to {maximum_purge_count} items"
				f" to respect minimum items setting ({minimum_items})"
			)
			purge_count = maximum_purge_count
		
		items_to_purge = []
		for purge_index in range(purge_count):
			
			#
			item_to_purge, item_ctime, item_age_seconds, item_age = self._pick_oldest_item(
				config=config, items=candidate_items
			)
			item_to_purge: Path
			
			candidate_items.remove(item_to_purge)
			
			self.info(
				f"Found next item to purge: ({purge_index + 1})"
				f" {item_to_purge.name}"
				f" ({item_age})"
			)
			
			#
			items_to_purge.append(item_to_purge)
		
		#
		self.info("Removing items")
		for item_to_purge in items_to_purge:
			
			item_to_purge: Path
			
			self.debug(f"Purging item: {item_to_purge.name}")
			
			self._remove_item(config=config, path=item_to_purge)
	
	def _rotate_path_for_maximum_age(self, config: ConfigFile, path: Path):
		
		assert path.is_dir(), f"Path should be a directory: {path}"
		
		if config.maximum_age:
			self.info(
				f"Rotating path for max age of {config.maximum_age} days: {path}"
			)
		else:
			self.info(
				f"Not configured to rotate for a maximum number of days."
			)
			return
		
		candidate_items = self._gather_rotation_candidates(config=config, path=path)
		minimum_items = self._determine_minimum_items(config=config)
		
		# Do we need to rotate anything out?
		if len(candidate_items) < minimum_items:
			self.info(
				f"Path only has {len(candidate_items)} items"
				f", which does not meet the minimum threshold of {minimum_items} items."
				f" Won't rotate this path."
			)
			return
		
		self.info(
			f"Examining {len(candidate_items)} items for deletion"
		)
		items_to_delete = []
		for item in candidate_items:
			
			age_seconds = self._detect_item_age_seconds(config=config, item=item)
			age_days = self._detect_item_age_days(config=config, item=item)
			age_formatted = Util.seconds_to_time_string(age_seconds)
			
			if age_days > config.maximum_age:
				self.info(
					f"[Old enough    ] {item.name} ({age_formatted})"
				)
				items_to_delete.append(item)
			else:
				self.info(
					f"[Not Old enough] {item.name} ({age_formatted})"
				)
		
		if len(items_to_delete) > 0:
			
			self.info("Removing old items ...")
			
			for item in items_to_delete:
				self._remove_item(config, item)
			
		else:
			self.info("No old items to remove")
	
	def _gather_rotation_candidates(self, config: ConfigFile, path: Path) -> [Path]:
		
		self.debug(f"Begin gathering rotation candidates for: {path}")
		
		candidates: [Path] = []
		
		for item_name in path.iterdir():
			
			item_path = path / item_name
			self.debug(f"Found an item: {item_name} ==> {item_path}")
			
			if config.target_type == "file":
				
				if not item_path.is_file():
					self.debug(f"Not a file; Skipping: {item_name}")
					continue
			
			elif config.target_type == "directory":
				
				if not item_path.is_dir():
					self.debug(f"Not a directory; Skipping: {item_name}")
					continue
			
			else:
				raise Exception(
					f"Unsupported target type: {config.target_type}"
				)
			
			candidates.append(item_path)
		
		return candidates
	
	def _pick_oldest_item(self, config: ConfigFile, items: [Path]) -> (Path, float, float, str):
		
		best_item = None
		best_ctime = None
		for item in items:
			
			ctime = self._detect_item_date(config, item)
			if best_ctime is None or ctime < best_ctime:
				best_ctime = ctime
				best_item = item
		
		age_seconds = self._detect_item_age_seconds(config, best_item)
		age_string = Util.seconds_to_time_string(age_seconds)

		return best_item, best_ctime, age_seconds, age_string
	
	@staticmethod
	def _detect_item_date(config: ConfigFile, item: Path) -> datetime.datetime:
		
		if config.date_detection == "file":
			ctime = datetime.datetime.fromtimestamp(
				item.stat().st_ctime, tz=datetime.timezone.utc
			)
		
		else:
			raise AssertionError(
				f"Unsupported date-detection option: {config.date_detection}"
			)
		
		return ctime
	
	def _detect_item_age_seconds(self, config: ConfigFile, item: Path) -> float:
		
		now = datetime.datetime.now()
		
		ctime = self._detect_item_date(config=config, item=item)
		delta = now - ctime.now()
		
		return delta.seconds
	
	def _detect_item_age_days(self, config: ConfigFile, item: Path) -> int:
		
		age_seconds = self._detect_item_age_seconds(
			config=config, item=item
		)
		age_days = int(age_seconds / 86400)
		
		return age_days
	
	def _remove_item(self, config: ConfigFile, path: Path):
		
		if path.is_file():
			
			self._remove_file(config=config, file_path=path)
			
		elif path.is_dir():
			
			self._remove_directory(config=config, dir_path=path)
			
		else:
			raise AssertionError(
				f"Don't know how to remove this item: {path}"
			)
	
	def _remove_file(self, config: ConfigFile, file_path: Path):
		
		if not file_path.is_file():
			raise Exception(
				f"Tried to remove a file, but this path isn't a file: {file_path}"
			)
		
		if self.__global_dry_run:
			
			self.info(f"Won't purge file during global-level dry run: {file_path}")
			
		elif config.dry_run is True:
			
			self.info(f"Won't purge file during config-level dry run: {file_path}")
			
		else:
			self.info(f"Purging file: {file_path}")
			file_path.unlink()
	
	def _remove_directory(self, config: ConfigFile, dir_path: Path):
		
		if not dir_path.is_dir():
			raise Exception(
				f"Tried to remove a directory"
				f", but this path isn't a directory: {dir_path}"
			)
		
		if self.__global_dry_run:
			
			self.info(f"Won't purge directory during global-level dry run: {dir_path}")
			
		elif config.dry_run:
			
			self.info(f"Won't purge directory during config-level dry run: {dir_path}")
			
		else:
			
			self.info(f"Purging directory: {dir_path}")
			shutil.rmtree(dir_path)
	
	def _determine_minimum_items(self, config) -> int:
		
		minimum_items = 0
		
		if config.minimum_items is not None:
			
			minimum_items = config.minimum_items
			
			self.info(
				f"Won't delete anything unless a minimum of {minimum_items} items were found"
			)
		
		else:
			self.info(
				"No minimum number of items specified"
				"; Will not enforce minimum item constraint."
			)
		
		return minimum_items

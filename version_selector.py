import os
import re
from abc import ABC, abstractmethod
from itertools import product

import pandas as pd

from config import Config
from repo import Repo


class AbstractSelectVersions(ABC):
    def __init__(self, repo, tags, versions, version_num, version_type, strict=False):
        self.repo = repo
        self.tags = tags
        self.versions = versions
        self.version_num = version_num
        self.versions_by_type = []
        self.versions_selected = []
        self.type = version_type
        self.strict = strict

    def select(self):
        self._get_versions_by_type(self.versions)
        self.tags = list(filter(lambda x: x.version in self.versions_by_type, self.tags))
        self._select_versions(self.repo, self.versions_by_type, self.tags)
        self._store_versions(self.repo)
        return self.versions_selected

    def _get_versions_by_type(self, versions):
        if self.type == "all":
            self.versions_by_type = versions
            return

        majors, minors, micros = [], [], []
        separators = [r'\.', r'\-', r'\_']
        template_base = [['([0-9])', '([0-9])([0-9])', '([0-9])$'], ['([0-9])', '([0-9])([0-9])$'],
                         ['([0-9])', '([0-9])', '([0-9])([0-9])$'], ['([0-9])([0-9])', '([0-9])$'],
                         ['([0-9])', '([0-9])', '([0-9])$'], ['([0-9])', '([0-9])$']]
        templates = []
        for base in template_base:
            templates.extend(list(map(lambda sep: sep.join(base), separators)))
        templates.extend(['([0-9])([0-9])([0-9])$', '([0-9])([0-9])$'])
        for version in versions:
            for template in templates:
                values = re.findall(template, version._name)
                if values:
                    values = list(map(int, values[0]))
                    if len(values) == 4:
                        micros.append(version)
                        major, minor1, minor2, micro = values
                        minor = 10 * minor1 + minor2
                    elif len(values) == 3:
                        micros.append(version)
                        major, minor, micro = values
                    else:
                        major, minor = values
                        micro = 0
                    if micro == 0:
                        minors.append(version)
                    if minor == 0 and micro == 0:
                        majors.append(version)
                    break


        if self.type == "majors":
            self.versions_by_type = majors
        elif self.type == "minors":
            self.versions_by_type = minors
        elif self.type == "micros":
            self.versions_by_type = micros
        else:
            raise Exception("Error: " + self.type + " not an option.")

    @abstractmethod
    def _select_versions(self, repo, versions_by_type, tags):
        pass

    @abstractmethod
    def _store_versions(versions, repo):
        pass


class BinSelectVersion(AbstractSelectVersions):
    def __init__(self, repo, tags, versions, version_num, version_type, strict, start=[5], stop=[100], step=[10]):
        super().__init__(repo, tags, versions, version_num, version_type, strict)
        self.start = start
        self.stop = stop
        self.step = step
        self.selected_versions = list()

    def _select_versions(self, repo, versions_by_type, tags):
        for start, stop, step in product(self.start, self.stop, self.step):
            bins = list(map(lambda x: list(), range(start, stop, step)))
            for tag in tags:
                bugged_files = len(list(filter(lambda x: "java" in x, tag.bugged_files)))
                java_files = len(list(filter(lambda x: "java" in x, tag.version_files)))
                if bugged_files * java_files == 0:
                    continue
                bugged_ratio = 1.0 * bugged_files / java_files
                bins[int(((bugged_ratio * 100) - start) / step) - 1].append(tag.version._name)
            for ind, bin_ in enumerate(bins):
                if len(bin_) < self.version_num:
                    continue
                selected_versions = list(bin_)
                configuration = {'start': start, 'step': step, 'stop': stop, 'versions': selected_versions}
                self.selected_versions.append(configuration)

    def _store_versions(self, repo):
        configuration = self.selected_versions[0]
        values = list(product([configuration['start']], [configuration['step']],
                              [configuration['stop']], configuration['versions']))
        columns = ["start", "step", "stop", "version"]
        df = pd.DataFrame(values, columns=columns)
        config = Config().config
        repository_data = config["CACHING"]["RepositoryData"]
        selected_versions = config["DATA_EXTRACTION"]["SelectedVersionsBin"]
        dir_path = os.path.join(repository_data, selected_versions)
        dir_path = Config.get_work_dir_path(dir_path)
        Config.assert_dir_exists(dir_path)
        path = os.path.join(dir_path, repo.github_name + ".csv")
        df.to_csv(path, index=False)


class QuadraticSelectVersion(AbstractSelectVersions):
    def __init__(self, repo, tags, versions, version_num, version_type, strict, min_ratio=0.10, max_ratio=0.30, min_num_commits=100):
        super().__init__(repo, tags, versions, version_num, version_type, strict)
        self.min_ratio = min_ratio
        self.max_ratio = max_ratio
        self.min_num_commits = min_num_commits

    def _select_versions(self, repo, versions_by_type, tags):

        def cond1(x, ratio): return x.bugged_ratio <= ratio
        def cond2(x, ratio): return x.bugged_ratio >= ratio
        def cond3(x, num_commits): return x.num_commits >= num_commits
        max_ratio, min_ratio = self.max_ratio, self.min_ratio
        min_num_commits = self.min_num_commits
        filtered_tags = []
        while len(filtered_tags) < self.version_num:
            if min_num_commits <= 0:
                raise self.NotEnoughVersions("Error: lower the num of versions.")

            filtered_tags = list(filter(lambda tag:
                                        cond1(tag, max_ratio) and
                                        cond2(tag, min_ratio) and
                                        cond3(tag, min_num_commits), tags))

            max_ratio += self.max_ratio / 10
            min_num_commits -= self.min_num_commits / 10

        if (not self.strict) or (self.strict and len(filtered_tags) == self.version_num):
            self.versions_selected = list(map(lambda x: x.version._name, filtered_tags))
            return

        # The #commits formula is f(x) = 100*x, f(x) > 0 and x > 0
        # The quadratic formula is:
        # f(x) = -100(x-0.2)^2+1, 0 <= f(x) <= 1 and 0.10 <= x <= 0.30

        min_num_commits = 100.00 * float(min(filtered_tags, key=lambda x: x.num_commits).num_commits)
        max_num_commits = 100.00 * float(max(filtered_tags, key=lambda x: x.num_commits).num_commits)
        def num_commits(x): return 100.0 * float(x.num_commits)

        commits_scores = list(map(lambda x: (num_commits(x) - min_num_commits)/(max_num_commits - min_num_commits),
                                  filtered_tags))
        ratio_scores = list(map(lambda x: (-100 * (x.bugged_ratio - 0.2)**2 + 1), filtered_tags))

        values = list(map(lambda x, y, z: (x, str(y + z)), filtered_tags, commits_scores, ratio_scores))
        values.sort(reverse=True, key=lambda x: x[1])
        selected = list(map(lambda x: x[0].version._name, values[:5]))
        self.versions_selected = selected

    class NotEnoughVersions(Exception):
        pass

    def _store_versions(self, repo):
        columns = ["version"]
        values = self.versions_selected
        df = pd.DataFrame(values, columns=columns)
        config = Config().config
        repository_data = config["CACHING"]["RepositoryData"]
        selected_versions = config["DATA_EXTRACTION"]["SelectedVersionsQuadratic"]
        dir_path = os.path.join(repository_data, selected_versions)
        dir_path = Config.get_work_dir_path(dir_path)
        Config.assert_dir_exists(dir_path)
        path = os.path.join(dir_path, repo.github_name + ".csv")
        df.to_csv(path, index=False)
        pass


class ConfigurationSelectVersion(AbstractSelectVersions):
    def __init__(self, repo, tags, versions, version_num, version_type):
        super().__init__(repo, tags, versions, version_num, version_type)
        self.configuration = r"""workingDir={WORKING_DIR}
            git={GIT_PATH}
            issue_tracker_product_name={PRODUCT_NAME}
            issue_tracker_url=https://issues.apache.org/jira
            issue_tracker=jira
            vers={VERSIONS}
            """

    def _select_versions(self, repo, versions_by_type, tags):
        versions_dict = {}
        for start, stop, step, versions in product([1, 5, 10], [100], [5, 10, 20], self.versions_by_type):
            bins = list(map(lambda x: list(), range(start, stop, step)))
            for tag in tags:
                bugged_files = len(list(filter(lambda x: "java" in x, tag.bugged_files)))
                java_files = len(list(filter(lambda x: "java" in x, tag.version_files)))
                if bugged_files * java_files == 0:
                    continue
                bugged_ratio = 1.0 * bugged_files / java_files
                bins[int(((bugged_ratio * 100) - start) / step) - 1].append(tag.version._name)
            for ind, bin_ in enumerate(bins):
                if len(bin_) < self.versions_num:
                    continue
                id = "{0}_{1}_{2}_{3}_{4}_{5}".format(repo.jira_key, start, stop, step, versions[0], ind)
                versions_dict[id] = repr(tuple(bin)).replace("'", "")

        self.selected_versions = versions_dict

    def _store_versions(self, repo):
        config = Config().config
        repository_data = config["CACHING"]["RepositoryData"]
        configuration_path = config["DATA_EXTRACTION"]["ConfigurationsPaths"]
        configuration_dir = os.path.join(repository_data, configuration_path)
        Config.assert_dir_exists(configuration_dir)
        working_dir = config["DATA_EXTRACTION"]["ConfigurationsWorkingDir"]
        Config.assert_dir_exists(working_dir)
        for id_ in self.selected_versions:
            path = os.path.join(configuration_dir, id_)
            with open(path, "wb") as file_:
                file_.write(self.configuration.format(WORKING_DIR=os.path.join(working_dir, id),
                                                      PRODUCT_NAME=repo.jira_key,
                                                      GIT_PATH=repo.local_path,
                                                      VERSIONS=self.selected_versions[id_]))
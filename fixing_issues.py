import git
import csv
import sys
csv.field_size_limit(sys.maxsize)
from commit import Commit
from versions import get_repo_versions, get_tag_by_name
from issues import get_jira_issues

def clean_commit_message(commit_message):
    if "git-svn-id" in commit_message:
        return commit_message.split("git-svn-id")[0]
    return commit_message


def commits_and_issues(repo, issues):
    def get_bug_num_from_comit_text(commit_text, issues_ids):
        s = commit_text.lower().replace(":", "").replace("#", "").replace("-", " ").replace("_", " ").split()
        for word in s:
            if word.isdigit():
                if word in issues_ids:
                    return word
        return "0"
    commits= []
    issues_ids = map(lambda issue: issue.key.split("-")[1], issues)
    for git_commit in repo.iter_commits():
        commit_text = clean_commit_message(git_commit.message)
        commits.append(Commit(git_commit, get_bug_num_from_comit_text(commit_text, issues_ids)))
    return commits


def get_data(gitPath, jira_url, jira_project_name):
    repo = git.Repo(gitPath)
    issues = get_jira_issues(jira_url, jira_project_name)
    return commits_and_issues(repo, issues)


def get_commits_between_versions(commits, versions):
    tags_commits = {}
    sorted_versions = sorted(versions, key=lambda version: version._commit._commit_date)
    for git_commit in commits:
        for current_version, next_version in zip(sorted_versions, sorted_versions[1:]):
            current_version_date = current_version._commit._commit_date
            next_version_date = next_version._commit._commit_date
            if git_commit._commit_date > current_version_date and git_commit._commit_date < next_version_date:
                tags_commits.setdefault(current_version, []).append(git_commit)
                break
    return tags_commits


def get_bugged_files_between_versions(gitPath, jira_url, jira_project_name, versions):
    commits = get_data(gitPath, jira_url, jira_project_name)
    tags_commits = get_commits_between_versions(filter(lambda commit: commit._bug_id != "0", commits), versions)
    tags_bugs = {}
    for tag in tags_commits:
        tags_bugs[tag] = set(reduce(list.__add__, map(lambda commit: commit._files, tags_commits[tag]), []))
    return tags_bugs


def save_bugs(out_file, gitPath, jira_url, jira_project_name, versions):
    tags_bugs = get_bugged_files_between_versions(gitPath, jira_url, jira_project_name, versions)
    with open(out_file, "wb") as f:
        writer = csv.writer(f)
        writer.writerow(["version_name", "#files in version", "#bugged files in version", "version_date"])
        writer.writerows([[tag._name, len(filter(lambda x: "java" in x, tag.version_files)), len(filter(lambda x: "java" in x,  files)), tag._commit._commit_date.strftime("%Y-%m-%d")] for tag, files in tags_bugs.items()])


def main(out_file, gitPath, jira_url, jira_project_name):
    commits = get_data(gitPath, jira_url, jira_project_name)
    with open(out_file, "wb") as f:
        writer = csv.writer(f)
        writer.writerows([c.to_list() for c in commits])

if __name__ == "__main__":
    # main(r"C:\Temp\commits2.csv", r"C:\Temp\example\airavata", r"http://issues.apache.org/jira", r"AIRAVATA")
    versions = map(lambda version: get_tag_by_name(r"C:\Temp\tika", version), ['1.8', '1.9-rc1', '1.10-rc1', '1.12-rc1', '1.13-rc1', '1.14-rc1'])
    # tags_bugged = get_bugged_files_between_versions(r"C:\Temp\tika", r"http://issues.apache.org/jira", r"TIKA", versions)
    # save_bugs(r"C:\Temp\bugs_tika4.csv", r"C:\Temp\tika", r"http://issues.apache.org/jira", r"TIKA", get_repo_versions(r"C:\Temp\tika"))
    save_bugs(r"C:\Temp\bugs_tika_versions_2.csv", r"C:\Temp\tika", r"http://issues.apache.org/jira", r"TIKA", versions)
    exit()
    # print tags_bugged
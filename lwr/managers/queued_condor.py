from re import search
from os.path import exists
from os import stat
from subprocess import Popen, PIPE, STDOUT, CalledProcessError, check_call

from lwr.managers.base import ExternalBaseManager

JOB_FILE_TEMPLATE = """#!/bin/sh
cd $working_directory
$command_line
echo $? > $return_code_path
"""

DEFAULT_QUERY_CLASSAD = dict(
    universe='vanilla',
    getenv='true',
    notification='NEVER',
)


class CondorQueueManager(ExternalBaseManager):
    """
    """
    manager_type = "queued_condor"

    def __init__(self, name, app, **kwds):
        super(CondorQueueManager, self).__init__(name, app, **kwds)
        self.user_log_sizes = {}
        self.state_cache = {}

    def launch(self, job_id, command_line):
        self._check_execution_with_tool_file(job_id, command_line)
        job_file_path = self._setup_job_file(job_id, command_line)
        query_params = DEFAULT_QUERY_CLASSAD.copy()
        submit_desc = []
        for k, v in query_params.items():
            submit_desc.append('%s = %s' % (k, v))
        submit_desc.append('executable = ' + job_file_path)
        submit_desc.append('output = ' + self._stdout_path(job_id))
        submit_desc.append('error = ' + self._stderr_path(job_id))
        log_path = self.__condor_user_log(job_id)
        open(log_path, 'w')  # Touch log file
        submit_desc.append('log = ' + log_path)
        submit_desc.append('queue')
        submit_file_contents = "\n".join(submit_desc)
        submit_file = self._write_job_file(job_id, "job.condor.submit", submit_file_contents)
        submit = Popen(('condor_submit', submit_file), stdout=PIPE, stderr=STDOUT)
        s_out, s_err = submit.communicate()
        if submit.returncode == 0:
            match = search('submitted to cluster (\\d+).', s_out)
            if match is None:
                s_out = 'Failed to find job id from condor_submit'
            else:
                external_id = match.group(1)
        else:
            raise Exception("condor_submit failed - %s" % s_out)
        self._register_external_id(job_id, external_id)

    def __condor_user_log(self, job_id):
        return self._job_file(job_id, 'job_condor.log')

    def _kill_external(self, external_id):
        try:
            check_call(('condor_rm', external_id))
        except CalledProcessError:
            pass

    def get_status(self, job_id):
        external_id = self._external_id(job_id)
        if not external_id:
            raise Exception("Failed to obtain external_id for job_id %s, cannot determine status." % job_id)
        log_path = self.__condor_user_log(job_id)
        if not exists(log_path):
            return 'complete'
        if external_id not in self.user_log_sizes:
            self.user_log_sizes[external_id] = -1
            self.state_cache[external_id] = 'queued'
        log_size = stat(log_path).st_size
        if log_size == self.user_log_sizes[external_id]:
            return self.state_cache[external_id]
        return self.__get_state_from_log(external_id, log_path)

    def __get_state_from_log(self, external_id, log_file):
        log_job_id = external_id.zfill(3)
        state = 'queued'
        with open(log_file, 'r') as fh:
            for line in fh:
                if '001 (' + log_job_id + '.' in line:
                    state = 'running'
                if '004 (' + log_job_id + '.' in line:
                    state = 'running'
                if '007 (' + log_job_id + '.' in line:
                    state = 'running'
                if '005 (' + log_job_id + '.' in line:
                    state = 'complete'
                if '009 (' + log_job_id + '.' in line:
                    state = 'complete'
            log_size = fh.tell()
        self.user_log_sizes[external_id] = log_size
        self.state_cache[external_id] = state
        return state
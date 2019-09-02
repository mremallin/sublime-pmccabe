import sublime
import sublime_plugin

import os
import subprocess
import sys
import threading
import time
import codecs
import signal
import collections
import functools
import re

ComplexityResult = collections.namedtuple("ComplexityResult",
                                          ["modified_complexity",
                                           "traditional_complexity",
                                           "num_statements",
                                           "first_line",
                                           "lines_in_function",
                                           "filename",
                                           "function_name"])
ComplexityLineRE = re.compile(
    r"^(?P<modified_complexity>\d+)\s+"
    "(?P<traditional_complexity>\d+)\s+(?P<num_statements>\d+)\s+"
    "(?P<first_line>\d+)\s+(?P<num_lines>\d+)\s+(?P<filename>.*):\s+"
    "(?P<function_name>.*)")


def parse_complexity_results(view, lines_to_parse):
    complexity_results = []
    for line in lines_to_parse:
        match = ComplexityLineRE.match(view.substr(line))
        if match:
            complexity_results.append((
                ComplexityResult(*match.groups()), line))

    return complexity_results


class ProcessListener(object):
    def on_data(self, proc, data):
        pass

    def on_finished(self, proc):
        pass


class AsyncProcess(object):
    def __init__(self, executable, file_path, listener):
        if not file_path:
            raise ValueError("Need a file to analyze")

        self.listener = listener
        self.killed = False
        self.start_time = time.time()

        # Hide the console window on Windows
        startupinfo = None
        if os.name == "nt":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

        if sys.platform == "win32":
            preexec_fn = None
        else:
            preexec_fn = os.setsid

        if sys.platform == "win32":
            self.proc = subprocess.Popen(
                [executable, "-v", file_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.PIPE,
                startupinfo=startupinfo,
                shell=False)
        elif sys.platform == "darwin" or sys.platform == "linux":
            self.proc = subprocess.Popen(
                [executable, "-v", file_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.PIPE,
                startupinfo=startupinfo,
                preexec_fn=preexec_fn,
                shell=False)

        if self.proc.stdout:
            threading.Thread(
                target=self.read_fileno,
                args=(self.proc.stdout.fileno(), True)
            ).start()

        if self.proc.stderr:
            threading.Thread(
                target=self.read_fileno,
                args=(self.proc.stderr.fileno(), False)
            ).start()

    def kill(self):
        if not self.killed:
            self.killed = True
            if sys.platform == "win32":
                # terminate would not kill process opened by the shell cmd.exe,
                # it will only kill cmd.exe leaving the child running
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                subprocess.Popen(
                    "taskkill /PID %d /T /F" % self.proc.pid,
                    startupinfo=startupinfo)
            else:
                os.killpg(self.proc.pid, signal.SIGTERM)
                self.proc.terminate()
            self.listener = None

    def poll(self):
        return self.proc.poll() is None

    def exit_code(self):
        return self.proc.poll()

    def read_fileno(self, fileno, execute_finished):
        decoder_cls = codecs.getincrementaldecoder(self.listener.encoding)
        decoder = decoder_cls('replace')
        while True:
            data = decoder.decode(os.read(fileno, 2**16))

            if len(data) > 0:
                if self.listener:
                    self.listener.on_data(self, data)
            else:
                try:
                    os.close(fileno)
                except OSError:
                    pass
                if execute_finished and self.listener:
                    self.listener.on_finished(self)
                break


class PmccabeCommand(sublime_plugin.WindowCommand, ProcessListener):
    BLOCK_SIZE = 2**14
    text_queue = collections.deque()
    text_queue_proc = None
    text_queue_lock = threading.Lock()

    def _get_pmccabe_executable(self):
        s = sublime.load_settings("pmccabe.sublime-settings")
        pmccabe_executable = s.get("pmccabe_executable", "/usr/bin/pmccabe")
        return pmccabe_executable

    def _get_high_complexity_threshold(self):
        s = sublime.load_settings("pmccabe.sublime-settings")
        return s.get("high_complexity_threshold", 15)

    def _get_medium_complexity_threshold(self):
        s = sublime.load_settings("pmccabe.sublime-settings")
        return s.get("medium_complexity_threshold", 7)

    def _get_output_highlighting_enabled(self):
        s = sublime.load_settings("pmccabe.sublime-settings")
        return s.get("output_highlighting", False)

    def run(self, kill=False, encoding="utf-8", quiet=False, **kwargs):
        # clear the text_queue
        with self.text_queue_lock:
            self.text_queue.clear()
            self.text_queue_proc = None

        if kill:
            if self.proc:
                self.proc.kill()
                self.proc = None
                self.append_string(None, "[Cancelled]")
            return

        view = self.window.active_view()
        self.output_panel = self.window.create_output_panel("pmccabe")
        self.window.run_command("show_panel", {"panel": "output.pmccabe"})

        self.encoding = encoding
        self.quiet = quiet
        self.debug_text = ""

        try:
            # Forward kwargs to AsyncProcess
            self.proc = AsyncProcess(self._get_pmccabe_executable(),
                                     view.file_name(), self, **kwargs)

            with self.text_queue_lock:
                self.text_queue_proc = self.proc

        except Exception as e:
            self.append_string(None, str(e) + "\n")
            self.append_string(None, self.debug_text + "\n")
            if not self.quiet:
                self.append_string(None, "[Finished]")

    def sort_results_into_buckets(self, results):
        output_regions = {
            "low_complexity": [],
            "medium_complexity": [],
            "high_complexity": []
        }

        for result, line_region in results:
            if int(result.modified_complexity) > self._get_high_complexity_threshold():
                output_regions["high_complexity"].append(line_region)
            elif int(result.modified_complexity) > self._get_medium_complexity_threshold():
                output_regions["medium_complexity"].append(line_region)
            else:
                output_regions["low_complexity"].append(line_region)

        return output_regions

    def highlight_results(self):
        output_lines = self.output_panel.lines(
            sublime.Region(0, self.output_panel.size()))
        results = parse_complexity_results(self.output_panel, output_lines)
        output_regions = self.sort_results_into_buckets(results)

        self.output_panel.add_regions(
            "Pmccabe_high_complexity",
            output_regions["high_complexity"],
            "invalid.illegal")
        self.output_panel.add_regions(
            "Pmccabe_medium_complexity",
            output_regions["medium_complexity"])
        self.output_panel.add_regions(
            "Pmccabe_low_complexity",
            output_regions["low_complexity"],
            "comment")

    def is_enabled(self, kill=False, **kwargs):
        if kill:
            return (self.proc is not None) and self.proc.poll()

        pmccabe_executable = self._get_pmccabe_executable()
        if not os.path.exists(pmccabe_executable):
            sublime.error_message("The pmccabe executable provided at '{}' "
                                  "does not exist".format(pmccabe_executable))
            return False

        return True

    def append_string(self, proc, str):
        was_empty = False
        with self.text_queue_lock:
            if proc != self.text_queue_proc and proc:
                # a second call to exec has been made before the first one
                # finished, ignore it instead of intermingling the output.
                proc.kill()
                return

            if len(self.text_queue) == 0:
                was_empty = True
                self.text_queue.append("")

            available = self.BLOCK_SIZE - len(self.text_queue[-1])

            if len(str) < available:
                cur = self.text_queue.pop()
                self.text_queue.append(cur + str)
            else:
                self.text_queue.append(str)

        if was_empty:
            sublime.set_timeout(self.service_text_queue, 0)

    def service_text_queue(self):
        is_empty = False
        with self.text_queue_lock:
            if len(self.text_queue) == 0:
                # this can happen if a new build was started, which will clear
                # the text_queue
                return

            characters = self.text_queue.popleft()
            is_empty = (len(self.text_queue) == 0)

        self.output_panel.run_command(
            'append',
            {'characters': characters, 'force': True, 'scroll_to_end': True})

        if not is_empty:
            sublime.set_timeout(self.service_text_queue, 1)

    def finish(self, proc):
        if not self.quiet:
            elapsed = time.time() - proc.start_time
            exit_code = proc.exit_code()
            if exit_code == 0 or exit_code is None:
                self.append_string(proc, "[Finished in %.1fs]" % elapsed)
            else:
                self.append_string(
                    proc,
                    "[Finished in %.1fs with exit code %d]\n" %
                    (elapsed, exit_code))
                self.append_string(proc, self.debug_text)

        if proc != self.proc:
            return

        if self._get_output_highlighting_enabled():
            self.highlight_results()

        sublime.status_message("Analysis finished")

    def on_data(self, proc, data):
        # Normalize newlines, Sublime Text always uses a single \n separator
        # in memory.
        data = data.replace('\r\n', '\n').replace('\r', '\n')

        self.append_string(proc, data)

    def on_finished(self, proc):
        sublime.set_timeout(functools.partial(self.finish, proc), 0)

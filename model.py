import re
from typing import Generator, List
from dataclasses import dataclass, field
from functools import reduce
from tempfile import NamedTemporaryFile
from PyQt5.QtCore import pyqtSignal


def validate_file_options(regex: str, delimiter: str, qualifier: str) -> tuple:
    error_messages = []
    try:
        re.compile(regex)
    except re.error:
        error_messages.append("Error while compiling regex")
    if len(delimiter.replace("\\t", "\t")) != 1:
        error_messages.append("Delimiter can only be a single character or \\t")
    if len(qualifier) > 1:
        error_messages.append("Qualifier can only be a single character or blank")
    return not bool(error_messages), "\n".join(error_messages)


def trim_indent(line: str) -> str:
    """ Removes indentation from multiline string """
    return re.sub(r"^ +", "", line, 0, re.MULTILINE).strip()


@dataclass
class BadEscape:
    qualifier: str
    record: str
    values: List[str]

    def escape_qualifiers(self, accumulator: str, value: str) -> str:
        return accumulator.replace(
            f"{self.qualifier}{value}{self.qualifier}",
            f"{self.qualifier}{value.replace(self.qualifier, self.qualifier * 2)}{self.qualifier}"
        )

    @property
    def fix_record(self) -> str:
        return reduce(self.escape_qualifiers, self.values, self.record)


@dataclass
class PeekResult:
    code: int
    path: str
    message: str
    delimiter: str = ""
    qualifier: str = ""
    encoding: str = ""


@dataclass
class AnalyzeResult:
    code: int
    temp_file: NamedTemporaryFile
    delimiter: str
    columns: List[str]
    overflow_lines: List[int] = field(default_factory=list)
    message: str = ""
    bad_delimiters: List[str] = field(default_factory=list)
    bad_escapes: List[BadEscape] = field(default_factory=list)


@dataclass
class BadDelimiterChange:
    row: int
    start: int
    end: int
    old_row: List[str]


class TextDataDoctor:

    def __init__(self,
                 record_start_regex: str,
                 path: str,
                 delimiter: str,
                 qualifier: str,
                 encoding: str):
        self.record_start_regex = re.compile(record_start_regex)
        self.path = path
        self.delimiter = delimiter
        self.qualifier = qualifier
        self.encoding = encoding
        self.overflow_lines = []
        self.all_qualified = True  # Should be False
        self.header_line = ""
        with open(path, encoding=encoding) as f:
            self.header_line = f.readline().rstrip("\r\n")
        self.columns = [
            column.replace(self.qualifier, "")
            for column in self.header_line.split(self.delimiter)
        ]
        self.header_delimiter_count = self.header_line.count(self.delimiter)

    @staticmethod
    def peek_file(path: str, progress_signal: pyqtSignal) -> PeekResult:
        qualifier = ""
        encoding = "utf8"
        lines: List[str] = []

        try:
            with open(path, "rb") as f:
                progress_signal.emit("Collecting byte header")
                byte_header = f.readline()
                progress_signal.emit("Checking for non 8 byte encoding")
                if 0 in byte_header:
                    return PeekResult(
                        -6,
                        path,
                        trim_indent("""
                        Found null byte in header line.
                        This usually means the file is not an 8 byte encoding.
                        Currently this application only supports 8 byte encodings""")
                    )
                header = byte_header.decode(encoding).rstrip("\r\n")
                progress_signal.emit("Reading lines to confirm utf8 encoding")
                for byte_line in f:
                    lines.append(byte_line.decode(encoding))
        except FileNotFoundError:
            return PeekResult(-1, path, "File not found")
        except UnicodeDecodeError:
            bad_lines = []
            encoding = "cp1252"
            progress_signal.emit("utf8 failed. Trying cp1252")
            with open(path, "rb") as f:
                header = f.readline().decode(encoding).rstrip("\r\n")
                lines = []
                for byte_line in f:
                    try:
                        line = byte_line.decode(encoding)
                        lines.append(line)
                    except UnicodeDecodeError:
                        bad_lines.append(byte_line)

            if bad_lines:
                PeekResult(
                    -2,
                    path,
                    trim_indent("""
                    Encoding is not ut8 and cp1252 failed as well.
                    This means the file contains an invalid byte that needs to be resolved:""")
                    + "".join([str(line) for line in bad_lines])
                )
        progress_signal.emit("Finding delimiter and qualifier")
        spacers = [
            spacer.replace(" ", "")
            for spacer in re.split(r"\w+", header)
            if spacer.replace(" ", "") != ""
        ]
        check_space = spacers[1] if len(spacers) > 1 else spacers[0]
        if re.search("[^ ]", check_space) is None:
            return PeekResult(-3, path, "Could not find delimiter")
        check_space = check_space.replace(" ", "")
        for char in check_space:
            if check_space.find(char) == check_space.rfind(char):
                delimiter = char
                break
        else:
            return PeekResult(-4, path, "Could not find delimiter")
        check_space = "".join(set(check_space.replace(delimiter, "")))
        if len(check_space) == 1:
            qualifier = check_space
        return PeekResult(1, path, "", delimiter, qualifier, encoding)

    @property
    def all_qualified_pattern(self) -> str:
        return f"{self.qualifier}{self.delimiter}{self.qualifier}"

    @property
    def start_pattern(self) -> str:
        return f"{self.delimiter}{self.qualifier}"

    @property
    def end_pattern(self) -> str:
        return f"{self.qualifier}{self.delimiter}"

    @property
    def filename(self) -> str:
        return re.search(r"(?<=/)[^./]+\..+$", self.path).group(0)

    def is_not_end_qualified_values(self, record: str, start: int, end: int) -> bool:
        return self.start_pattern in record[start: end] \
               and self.end_pattern in record[start: end] \
               and start < end

    def find_value_end(self, record: str, end_position: int) -> int:
        result = end_position
        next_start = record.find(self.start_pattern, end_position + 1)
        next_end = record.find(self.end_pattern, end_position + 1)
        if next_end != -1:
            if (next_start != -1 and next_end < next_start) or next_start == -1:
                result = self.find_value_end(record, next_end)
        return result

    def get_qualifier_values(self, record: str) -> Generator[str, None, None]:
        if not self.qualifier:
            raise AttributeError("Tried to get qualified values for file without qualifiers")
        if not record:
            raise AttributeError("Tried to get qualified values for a blank record")
        start = 0
        end = len(record)
        if record[0] == self.qualifier and self.end_pattern in record:
            temp_start = record[1:].index(self.end_pattern)
            yield record[1: temp_start]
            start = temp_start
        if record[-1] == self.qualifier and self.start_pattern in record:
            last_pattern = record[:-1].rindex(self.start_pattern)
            yield record[last_pattern + 1: end - 1]
            end = last_pattern + 1
        loop_counter = 0
        while self.is_not_end_qualified_values(record, start, end):
            try:
                value_start = record.index(self.start_pattern, start)
                end_position = record.index(self.end_pattern, value_start)
                value_end = self.find_value_end(record, end_position)
                yield record[value_start + 2: value_end]
                start = value_end + 1
            except IndexError as ex:
                print(ex)
            loop_counter += 1
            if loop_counter > 100:
                raise Exception("Too many while loops")

    def non_escaped_qualifiers(self, value: str) -> bool:
        return any(
            [
                match.count(self.qualifier) % 2 != 0
                for match in re.findall(
                    f"(?<=[^{self.qualifier}]){self.qualifier}+(?=[^{self.qualifier}])",
                    value
                )
            ]
        )

    def get_records(self) -> Generator[str, None, None]:
        """Generates each record from the file to analyze"""
        self.overflow_lines = []
        with open(self.path, "r", encoding=self.encoding) as f:
            f.readline()
            record = ""
            for i, line in enumerate(f):
                # Removes all newline characters at end of record
                line = line.rstrip("\r\n")

                # If the line meets the regex criteria the user specified for a record, the
                # line is appended to cleaned_lines
                if self.record_start_regex.match(line):
                    if record:
                        yield record
                    record = line
                    continue

                # If the cleaned line is blank, append that line to cleaned_lines and continue
                if not line:
                    record += f"\r{line}"
                    self.overflow_lines.append(i+2)
                    continue
                elif self.qualifier:
                    # Find the index of the last start and last end pattern in last_record
                    last_start = record.rfind(self.start_pattern)
                    last_end = record.rfind(self.end_pattern)
                    check_exp = (
                            record[-1] != self.qualifier
                            and last_start != -1
                            and last_start > last_end
                    )
                    if check_exp:
                        record += f"\r{line}"
                        self.overflow_lines.append(i+2)
                        continue
                # If the current line starts with some letter or number then a ')' or '.' then
                # the line is probably a list for a comment field. Append to the last record
                if re.match(r"^\w+[).] ", line):
                    record += f"\r{line}"
                    self.overflow_lines.append(i+2)
                # Check if the delimiter count in the line is the same as the header line.
                # If not, it is added as an overflow line to the last record
                elif line.count(self.delimiter) != self.header_delimiter_count:
                    record += f"\r{line}"
                    self.overflow_lines.append(i+2)
                else:
                    yield record
                    record = line
            yield record

    def analyze_file(self):
        self.overflow_lines = []
        bad_escapes: List[BadEscape] = []
        bad_delimiters: List[str] = []
        too_few_delimiters = False
        temp_file = NamedTemporaryFile(
            mode="w",
            encoding="utf8",
            suffix=".csv",
            delete=False,
            newline="\n"
        )

        temp_file.write(f"{self.header_line}\n")
        for record in self.get_records():
            is_bad_record = False
            if self.qualifier in record and self.qualifier:
                if self.all_qualified:
                    record = re.sub(f"{self.delimiter}$", "", record)
                if self.all_qualified:
                    checks = record[1:-1].split(self.all_qualified_pattern)
                else:
                    checks = self.get_qualifier_values(record)
                result = [check for check in checks if self.non_escaped_qualifiers(check)]

                if result:
                    bad_escapes.append(BadEscape(self.qualifier, record, result))
                    is_bad_record = True

            delimiter_count = record.count(self.delimiter)
            if delimiter_count != self.header_delimiter_count:
                if self.qualifier in record and self.qualifier:
                    if self.all_qualified:
                        delimiter_count = len(record.split(self.all_qualified_pattern)) - 1
                    else:
                        delimiter_count -= sum(
                            [
                                value.count(self.delimiter)
                                for value in self.get_qualifier_values(record)
                            ]
                        )
                    if delimiter_count != self.header_delimiter_count:
                        bad_delimiters.append(record)
                        is_bad_record = True
                        too_few_delimiters = delimiter_count < self.header_delimiter_count
                else:
                    bad_delimiters.append(record)
                    is_bad_record = True
                    too_few_delimiters = delimiter_count < self.header_delimiter_count
            if not is_bad_record:
                temp_file.write(f"{record}\n")
        temp_file.writelines([bad_escape.fix_record for bad_escape in bad_escapes])
        if bad_escapes and bad_delimiters:
            code = -1
            message = """
            Non-escaped qualifier and records with improper delimiters exist.
            No fix is available since assumptions cannot be made without error possibly arising.
            Please contact data owner to report this issue or try a new record start Regex"""
        elif bad_escapes:
            code = -2
            message = """
            Non-escaped qualifiers exist within the data.
            The issues have been resolved and the resulting fixed file can be exported"""
        elif bad_delimiters and not self.qualifier and not too_few_delimiters:
            code = -3
            message = """
            Records with improper delimiters exist.
            To resolve these instance follow the steps in the fix file tab to merge values that
            appear to contain the delimiter but are not qualified to retain the original integrity
            of the data. More information can be found in the documentation"""
        elif bad_delimiters and too_few_delimiters:
            code = -4
            message = """
            Records with improper delimiters exist.
            However, there are records with too few delimiters. This is a case where the application
            cannot resolve the issue since we cannot infer the intended data structure. A possible
            solution could be a more precise/encompassing records start regex to better categorize 
            records. If all else fails please contact the data owner"""
        elif bad_delimiters and self.qualifier:
            code = -5
            message = """
            Records with improper delimiters exist.
            However, a qualifier is present so we cannot merge and qualify values to resolve this
            issue. This may point to a bad record start regex so a rework of that might be needed.
            If not, please contact the data owner"""
        elif not bad_delimiters and not bad_escapes:
            if self.overflow_lines and not self.qualifier:
                code = -6
                message = """
                No issues found with the records.
                However, not qualifier was set but overflow of records was detected. This means most
                text data parsers might not be able to read this file so it would be best to export
                the file to qualify the file and properly structure the data"""
            else:
                code = 1
                message = "No fix needed!"
        else:
            code = -7
            message = """
            Unexpected error occurred. Pleas report this case and subsequent logs to
            the developer"""

        temp_file.close()
        return AnalyzeResult(
            code=code,
            temp_file=temp_file,
            delimiter=self.delimiter,
            columns=self.columns,
            overflow_lines=self.overflow_lines,
            message=trim_indent(message),
            bad_delimiters=bad_delimiters,
            bad_escapes=bad_escapes
        )

from dataclasses import dataclass
import argparse
from pathlib import Path
from typing import Callable
from typing_extensions import List
import math
import os
from itertools import chain
from functools import cmp_to_key

NAME_LEN = 70
ADDR_LEN = 15


@dataclass
class Reader:
    data: bytes
    ptr: int = 0

    def read_le(self, count: int) -> int:
        return sum(0x100**i * v for i, v in enumerate(self.read_bytes(count)))

    def read_str(self, length_count: int) -> str:
        length = self.read_le(length_count)
        raw_string = self.read_bytes(length)
        return raw_string.decode("utf-8")

    def read_bytes(self, count: int) -> bytes:
        val = self.data[self.ptr : self.ptr + count]
        self.ptr += count
        return val

    def bytes_at(self, addr: int, count: int) -> bytes:
        return self.data[addr : addr + count]

    def assertion(self, data: bytes, reason: str):
        assert self.read_bytes(len(data)) == data, reason


@dataclass
class Writer:
    data: bytes = b""

    def write_le(self, value: int, length: int):
        self.write_bytes(value.to_bytes(length))

    def write_str(self, string: bytes, length_count: int):
        self.write_le(len(string), length_count)
        self.write_bytes(string)

    def write_bytes(self, data: bytes):
        self.data += data


parser = argparse.ArgumentParser(
    prog="wak", description="Compress and Decompress wak files"
)
parser.add_argument("-w", "--wak", help="The wak file to read / write to")
parser.add_argument("-d", "--dir", help="The directory to read / write to")
parser.add_argument(
    "-c",
    "--compress",
    help="Compress to wak instead of decompressing from",
    action="store_true",
)
parser.add_argument(
    "-v",
    "--verbose",
    help="Print info about what is being done to each file",
    action="store_true",
)


@dataclass
class Arguments:
    wak: Path
    dir: Path
    compress: bool
    verbose: bool


parsed = parser.parse_args()
if parsed.wak is None or parsed.dir is None:
    raise Exception("Both wak and dir must be specified")

args = Arguments(
    wak=Path(parsed.wak),
    dir=Path(parsed.dir),
    compress=parsed.compress,
    verbose=parsed.verbose,
)

if args.verbose:
    print(args)


def prettify_bytes(num: int) -> str:
    prefixes = ["B", "KiB", "MiB", "GiB"]
    if num == 0:
        return "0B"
    category = math.floor(math.log(num, 1024))
    num /= 1024**category
    num_str = f"{num:.0f}" if category == 0 else f"{num:.2f}"
    return f"{num_str}{prefixes[category]}"


@dataclass
class File:
    path: str
    content: bytes


def parse_wak(wak: Path, verbose: bool) -> List[File]:
    reader = Reader(data=open(wak, "rb").read())
    reader.assertion(b"\0\0\0\0", "header start")
    file_count = reader.read_le(4)
    first_file = reader.read_le(4)
    reader.assertion(b"\0\0\0\0", "header end")

    def display(name: str, addr: str, size: str):
        if verbose:
            print(f"{name:<{NAME_LEN}} {addr:<{ADDR_LEN}} {size}")

    display("Path", "Address", "Size")

    files: List[File] = []

    for _ in range(file_count):
        addr = reader.read_le(4)
        size = reader.read_le(4)
        path = reader.read_str(4)
        content = reader.bytes_at(addr, size)
        files.append(File(path, content))
        display(path, hex(addr), prettify_bytes(size))

    return files


def cmp_to_cmp[T](fn: Callable[[T, T], bool]) -> Callable[[T, T], int]:
    return lambda a, b: -1 if fn(a, b) else (1 if fn(b, a) else 0)


def dir_to_files(dir: Path, verbose: bool) -> List[File]:

    def path_cmp(a: Path, b: Path) -> bool:
        if a.is_dir() and not b.is_dir():
            return False
        if b.is_dir() and not a.is_dir():
            return True
        return a < b

    def impl(root: Path, dir: Path, verbose: bool) -> List[File]:
        return list(
            chain.from_iterable(
                [
                    (
                        impl(root, x, verbose)
                        if x.is_dir()
                        else [
                            File(
                                str(x.relative_to(root)),
                                open(x, "rb").read(),
                            )
                        ]
                    )
                    for x in sorted(
                        (dir / y for y in os.listdir(dir)),
                        key=cmp_to_key(cmp_to_cmp(path_cmp)),
                    )
                ]
            )
        )

    return impl(dir, dir, verbose)


def save_wak(wak: Path, files: List[File], verbose: bool):
    writer = Writer()
    if args.verbose:
        for file in files:
            print(f"{file.path:<{NAME_LEN}} {prettify_bytes(len(file.content))}")

    # addr + size + len
    start_offset = sum(12 + len(file.path) for file in files)
    if verbose:
        print(hex(start_offset))

    writer.write_bytes(b"\0\0\0\0")
    writer.write_le(len(files), 4)
    writer.write_le(len(files), 4)
    writer.write_bytes(b"\0\0\0\0")

    open(wak, "wb").write(writer.data)


if args.compress:
    files = dir_to_files(args.dir, args.verbose)
    save_wak(args.wak, files, args.verbose)
else:
    files = parse_wak(args.wak, args.verbose)
    for file in files:
        path = args.dir / file.path
        os.makedirs(path.parent, exist_ok=True)
        open(path, "wb").write(file.content)

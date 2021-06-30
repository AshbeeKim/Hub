from hub.core.storage.cachable import Cachable
from typing import List, Optional, Sequence, Tuple
import numpy as np
from io import BytesIO
from math import ceil

from hub.core.meta.encode.shape import ShapeEncoder
from hub.core.meta.encode.byte_positions import BytePositionsEncoder

from hub.constants import DEFAULT_CHUNK_MAX_SIZE


class Chunk(Cachable):
    """A Chunk should only be provided data to store in bytes form, alongside the meta information (like shape/num_samples). The
    byte ranges are to be generated by this chunk, and it can also spawn new chunks as needed."""

    def __init__(self, max_data_bytes: int = DEFAULT_CHUNK_MAX_SIZE):
        # no need to load these encoders, if `frombuffer` is called, it will override them.
        self.index_shape_encoder = ShapeEncoder()
        self.index_byte_range_encoder = BytePositionsEncoder()

        self.max_data_bytes = max_data_bytes
        self.min_data_bytes_target = max_data_bytes // 2

        self.data = bytearray()

        self.next_chunk = None

    @property
    def num_samples(self):
        raise NotImplementedError

    @property
    def num_data_bytes(self):
        return len(self.data)

    @property
    def has_space(self):
        return self.num_data_bytes < self.min_data_bytes_target

    def extend(
        self,
        incoming_buffer: memoryview,
        num_samples: int,
        sample_shape: Tuple[int],
        _leftover_buffer_from_previous_chunk: bool = False,
    ) -> Tuple:
        # TODO: docstring

        if self.next_chunk is not None:
            # TODO: exceptions.py
            raise Exception(
                "Cannot extend a chunk that is connected to the next chunk."
            )

        if not self.has_space:
            # TODO: exceptions.py
            raise Exception("Cannot extend a chunk that has no space left.")

        incoming_num_bytes = len(incoming_buffer)

        if not _leftover_buffer_from_previous_chunk:
            self._update_headers(incoming_num_bytes, num_samples, sample_shape)

        processed_num_bytes = self._fill(incoming_buffer)

        if processed_num_bytes >= incoming_num_bytes:
            # this chunk was able to store all incoming bytes!
            return tuple()

        print(self.num_data_bytes)
        print(len(incoming_buffer))

        """
        # extracted chunk engine logic from `hub.core.chunk_engine.write`'s `write_bytes` function
        # need to implement this in a class factory esque way

        if _chunk_has_space(last_chunk, tensor_meta.chunk_size):
            last_chunk_size = len(last_chunk)
            chunk_ct_content = _min_chunk_ct_for_data_size(len(content))

            extra_bytes = min(len(content), DEFAULT_CHUNK_MAX_SIZE - last_chunk_size)
            combined_chunk_ct = _min_chunk_ct_for_data_size(len(content) + last_chunk_size)

            if combined_chunk_ct == chunk_ct_content:  # combine if count is same
                start_byte = index_meta.entries[-1]["end_byte"]
                end_byte = start_byte + extra_bytes

                chunk_content = bytearray(last_chunk) + content[0:extra_bytes]
                _write_chunk(chunk_content, storage, chunk_names, key, last_chunk_name)

                content = content[extra_bytes:]

        while len(content) > 0:
            end_byte = min(len(content), DEFAULT_CHUNK_MAX_SIZE)

            chunk_content = content[:end_byte]  # type: ignore
            _write_chunk(chunk_content, storage, chunk_names, key)

            content = content[end_byte:]

        index_meta.add_entry(
            chunk_names=chunk_names,
            start_byte=start_byte,
            end_byte=end_byte,
            **extra_sample_meta,
        )
        """

        raise NotImplementedError

    def _fill(self, incoming_buffer: memoryview) -> int:
        # TODO: docstring

        incoming_num_bytes = len(incoming_buffer)

        min_chunks_for_incoming_bytes = self._min_chunks_required_for_num_bytes(
            incoming_num_bytes
        )
        min_chunks_for_incoming_and_current_bytes = (
            self._min_chunks_required_for_num_bytes(
                incoming_num_bytes + self.num_data_bytes
            )
        )
        incoming_num_bytes_that_will_fit = min(
            incoming_num_bytes, self.max_data_bytes - self.num_data_bytes
        )
        if min_chunks_for_incoming_bytes == min_chunks_for_incoming_and_current_bytes:
            self.data += incoming_buffer[incoming_num_bytes_that_will_fit:]

        return incoming_num_bytes_that_will_fit

    def _min_chunks_required_for_num_bytes(self, num_bytes: int) -> int:
        """Calculates the minimum number of chunks in which data with length of `num_bytes` can be fit."""
        return ceil(num_bytes / self.max_data_bytes)

    def _spawn_chunk(self):
        # TODO: docstring

        if self.next_chunk is not None:
            # TODO: exceptions.py
            raise Exception("A chunk has already been spawned for this one.")

        chunk = Chunk(self.max_data_bytes)
        self.next_chunk = chunk
        return chunk

    def _update_headers(
        self, incoming_num_bytes: int, num_samples: int, sample_shape: Sequence[int]
    ):
        # TODO: docstring

        _validate_incoming_buffer(incoming_num_bytes, num_samples)

        num_bytes_per_sample = incoming_num_bytes // num_samples
        self.index_shape_encoder.add_shape(sample_shape, num_samples)
        self.index_byte_range_encoder.add_byte_position(
            num_bytes_per_sample, num_samples
        )

    def numpy(self):
        raise NotImplementedError

    def __getitem__(self, sample_index: int):
        raise NotImplementedError

    def __eq__(self, o: object) -> bool:
        raise NotImplementedError

    def __len__(self):
        # TODO: this should not call `tobytes` because it will be slow. should calculate the amount of bytes this chunk takes up in total. (including headers)
        raise NotImplementedError

    def tobytes(self) -> bytes:
        out = BytesIO()
        np.savez(
            out,
            index_shape_encoder=self.index_shape_encoder,
            index_byte_range_encoder=self.index_byte_range_encoder,
            data=self.data,
        )
        out.seek(0)
        return out.read()

    @classmethod
    def frombuffer(cls, buffer: bytes):
        instance = super().frombuffer(buffer)

        # TODO: this should also set `next_chunk`

        raise NotImplementedError
        return instance


def _validate_incoming_buffer(
    incoming_num_bytes: bytes,
    num_samples: int,
):
    if num_samples <= 0:
        raise ValueError(
            f"The number of samples a buffer can represent has to be greater than 0. Got {num_samples}"
        )

    if incoming_num_bytes % num_samples != 0:
        raise ValueError(
            f"Incoming buffer length should be perfectly divisible by the number of samples it represents. length={incoming_num_bytes}, num_samples={num_samples}"
        )

from typing import Any, List
from hub.core.meta.encode.base_encoder import Encoder, LAST_SEEN_INDEX_COLUMN
from hub.constants import ENCODING_DTYPE, UUID_SHIFT_AMOUNT
from hub.util.exceptions import ChunkIdEncoderError
from hub.core.storage.cachable import Cachable
import numpy as np
from uuid import uuid4
from hub.core.serialize import serialize_chunkids, deserialize_chunkids


CHUNK_ID_COLUMN = 0


class ChunkIdEncoder(Encoder, Cachable):
    def tobytes(self) -> memoryview:
        return serialize_chunkids(self.version, [self._encoded])

    @staticmethod
    def name_from_id(id: ENCODING_DTYPE) -> str:
        """Returns the hex of `id` with the "0x" prefix removed. This is the chunk's name and should be used to determine the chunk's key.
        Can convert back into `id` using `id_from_name`. You can get the `id` for a chunk using `__getitem__`."""

        return hex(id)[2:]

    @staticmethod
    def id_from_name(name: str):
        """Returns the 64-bit integer from the hex `name` generated by `name_from_id`."""

        return int("0x" + name, 16)

    def get_name_for_chunk(self, chunk_index: int) -> str:
        """Gets the name for the chunk at index `chunk_index`. If you need to get the name for a chunk from a sample index, instead
        use `__getitem__`, then `name_from_id`."""

        chunk_id = self._encoded[:, CHUNK_ID_COLUMN][chunk_index]
        return ChunkIdEncoder.name_from_id(chunk_id)

    @classmethod
    def frombuffer(cls, buffer: bytes):
        instance = cls()
        if not buffer:
            return instance
        version, ids = deserialize_chunkids(buffer)
        if ids.nbytes:
            instance._encoded = ids
        instance.version = version
        return instance

    @property
    def num_chunks(self) -> int:
        if self.num_samples == 0:
            return 0
        return len(self._encoded)

    def generate_chunk_id(self) -> ENCODING_DTYPE:
        """Generates a random 64bit chunk ID using uuid4. Also prepares this ID to have samples registered to it.
        This method should be called once per chunk created.

        Returns:
            ENCODING_DTYPE: The random chunk ID.
        """

        id = ENCODING_DTYPE(uuid4().int >> UUID_SHIFT_AMOUNT)

        if self.num_samples == 0:
            self._encoded = np.array([[id, -1]], dtype=ENCODING_DTYPE)

        else:
            last_index = self.num_samples - 1

            new_entry = np.array(
                [[id, last_index]],
                dtype=ENCODING_DTYPE,
            )
            self._encoded = np.concatenate([self._encoded, new_entry])

        return id

    def register_samples(self, num_samples: int):  # type: ignore
        """Registers samples to the chunk ID that was generated last with the `generate_chunk_id` method.
        This method should be called at least once per chunk created.

        Args:
            num_samples (int): The number of samples the last chunk ID should have added to it's registration.

        Raises:
            ValueError: `num_samples` should be non-negative.
            ChunkIdEncoderError: Must call `generate_chunk_id` before registering samples.
            ChunkIdEncoderError: `num_samples` can only be 0 if it is able to be a sample continuation accross chunks.
        """

        super().register_samples(None, num_samples)

    def translate_index_relative_to_chunks(self, global_sample_index: int) -> int:
        """Converts `global_sample_index` into a new index that is relative to the chunk the sample belongs to.

        Example:
            Given: 2 sampes in chunk 0, 2 samples in chunk 1, and 3 samples in chunk 2.
            >>> self.num_samples
            7
            >>> self.num_chunks
            3
            >>> self.translate_index_relative_to_chunks(0)
            0
            >>> self.translate_index_relative_to_chunks(1)
            1
            >>> self.translate_index_relative_to_chunks(2)
            0
            >>> self.translate_index_relative_to_chunks(3)
            1
            >>> self.translate_index_relative_to_chunks(6)
            2

        Args:
            global_sample_index (int): Index of the sample relative to the containing tensor.

        Returns:
            int: local index value between 0 and the amount of samples the chunk contains - 1.
        """

        ls = self.__getitem__(global_sample_index, return_row_index=True)  # type: ignore

        assert len(ls) == 1  # this method should only be called for non tiled samples
        chunk_index = ls[0][1]

        if chunk_index == 0:
            return global_sample_index

        current_entry = self._encoded[chunk_index - 1]  # type: ignore
        last_num_samples = current_entry[LAST_SEEN_INDEX_COLUMN] + 1

        return int(global_sample_index - last_num_samples)

    def _validate_incoming_item(self, _, num_samples: int):
        if num_samples < 0:
            raise ValueError(
                f"Cannot register negative num samples. Got: {num_samples}"
            )

        if self.num_samples == 0:
            raise ChunkIdEncoderError(
                "Cannot register samples because no chunk IDs exist."
            )

        if num_samples == 0 and self.num_chunks < 2:
            raise ChunkIdEncoderError(
                "Cannot register 0 num_samples (signifying a partial sample continuing the last chunk) when no last chunk exists."
            )

        # note: do not call super() method (num_samples can be 0)

    def _derive_next_last_index(self, last_index: ENCODING_DTYPE, num_samples: int):
        # this operation will trigger an overflow for the first addition, so supress the warning
        np.seterr(over="ignore")
        new_last_index = last_index + ENCODING_DTYPE(num_samples)
        np.seterr(over="warn")

        return new_last_index

    def _combine_condition(self, *args) -> bool:
        """Always returns True because sample registration can always be done. Used in base encoder `register_samples`."""

        return True

    def _derive_value(self, row: np.ndarray, *_) -> np.ndarray:
        return row[CHUNK_ID_COLUMN]

    def __setitem__(self, *args):
        raise NotImplementedError(
            "There is no reason for ChunkIdEncoder to be updated now."
        )

    def __getitem__(
        self, local_sample_index: int, return_row_index: bool = False
    ) -> Any:
        """Derives the value at `local_sample_index`.

        Args:
            local_sample_index (int): Index of the sample for the desired value.
            return_row_index (bool): If True, the index of the row that the value was derived from is returned as well.
                Defaults to False.

        Returns:
            Any: Either just a singular derived value, or a tuple with the derived value and the row index respectively.
        """

        row_index = self.translate_index(local_sample_index)

        output: List[Any] = []
        value = self._derive_value(
            self._encoded[row_index], row_index, local_sample_index
        )
        if return_row_index:
            output.append((value, row_index))
        else:
            output.append(value)
        row_index += 1

        while row_index < len(self._encoded):
            if self._encoded[row_index][1] == local_sample_index:
                value = self._derive_value(
                    self._encoded[row_index], row_index, local_sample_index
                )
                row_index += 1
                if return_row_index:
                    output.append((value, row_index))
                else:
                    output.append(value)
            else:
                break
        return output

    def _num_samples_in_last_chunk(self):
        if len(self._encoded) == 0:
            return 0
        elif len(self._encoded) == 1:
            return self._encoded[-1][LAST_SEEN_INDEX_COLUMN] + 1
        else:
            return (
                self._encoded[-1][LAST_SEEN_INDEX_COLUMN]
                - self._encoded[-2][LAST_SEEN_INDEX_COLUMN]
            )

    def _pop(self) -> List[ENCODING_DTYPE]:
        """Pops the last sample added to the encoder and returns ids of chunks to be deleted from storage."""
        chunk_ids_for_last_sampe = self[-1]
        if len(chunk_ids_for_last_sampe) > 1:
            self._encoded = self._encoded[: -len(chunk_ids_for_last_sampe)]
            return chunk_ids_for_last_sampe
        elif self._num_samples_in_last_chunk() == 1:
            self._encoded = self._encoded[:-1]
            return chunk_ids_for_last_sampe
        else:
            self._encoded[-1, LAST_SEEN_INDEX_COLUMN] -= 1
            return []

from hub.util.slice import merge_slices


class Tensor:
    def __init__(self, uuid: str, tensor_slice: slice = slice(None)):
        """Initialize a new tensor.

        Note:
            This operation does not create a new tensor in the backend,
            and should normally only be performed by Hub internals.

        Args:
            uuid (str): The internal identifier for this tensor.
            tensor_slice (slice, optional): The slice object restricting the view of this tensor.
        """
        self.uuid = uuid
        self.slice = tensor_slice
        self.shape = (0,)  # Dataset should pass down relevant metadata

    def __len__(self):
        """Return the length of the primary axis"""
        return self.shape[0]

    def __getitem__(self, tensor_slice: slice):
        new_slice = merge_slices(self.slice, tensor_slice)
        return Tensor(self.uuid, new_slice)

    def __iter__(self):
        for i in range(len(self)):
            yield self[i]

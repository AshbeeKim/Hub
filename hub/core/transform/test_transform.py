import hub
import pytest
import numpy as np
from click.testing import CliRunner
from hub.core.storage.memory import MemoryProvider
from hub.util.remove_cache import remove_memory_cache
from hub.util.check_installation import ray_installed
from hub.util.exceptions import InvalidOutputDatasetError, TransformError
from hub.tests.common import parametrize_num_workers
from hub.tests.dataset_fixtures import enabled_datasets, enabled_non_gcs_datasets
from hub.util.transform import get_pbar_description
import sys
import hub


# TODO progressbar is disabled while running tests on mac for now
if sys.platform == "darwin":
    defs = hub.core.transform.transform.Pipeline.eval.__defaults__  # type: ignore
    defs = defs[:-1] + (False,)
    hub.core.transform.transform.Pipeline.eval.__defaults__ = defs  # type: ignore

    defs = hub.core.transform.transform.TransformFunction.eval.__defaults__  # type: ignore
    defs = defs[:-1] + (False,)
    hub.core.transform.transform.TransformFunction.eval.__defaults__ = defs  # type: ignore


# github actions can only support 2 workers
TRANSFORM_TEST_NUM_WORKERS = 2

# github actions can only support 2 workers
TRANSFORM_TEST_NUM_WORKERS = 2

all_compressions = pytest.mark.parametrize("sample_compression", [None, "png", "jpeg"])

schedulers = ["threaded", "processed"]
schedulers = schedulers + ["ray"] if ray_installed() else schedulers
all_schedulers = pytest.mark.parametrize("scheduler", schedulers)


@hub.compute
def fn1(sample_in, samples_out, mul=1, copy=1):
    for _ in range(copy):
        samples_out.image.append(np.ones((337, 200)) * sample_in * mul)
        samples_out.label.append(np.ones((1,)) * sample_in * mul)


@hub.compute
def fn2(sample_in, samples_out, mul=1, copy=1):
    for _ in range(copy):
        samples_out.image.append(sample_in.image.numpy() * mul)
        samples_out.label.append(sample_in.label.numpy() * mul)


@hub.compute
def fn3(sample_in, samples_out, mul=1, copy=1):
    for _ in range(copy):
        samples_out.image.append(np.ones((1310, 2087)) * sample_in * mul)
        samples_out.label.append(np.ones((13,)) * sample_in * mul)


@hub.compute
def fn4(sample_in, samples_out):
    samples_out.image.append(sample_in.image)
    samples_out.image.append(sample_in.image.numpy() * 2)
    samples_out.label.append(sample_in.label)
    samples_out.label.append(sample_in.label.numpy() * 2)


@hub.compute
def fn5(sample_in, samples_out, mul=1, copy=1):
    for _ in range(copy):
        samples_out.x["y"].z.image.append(sample_in.z.y.x.image.numpy() * mul)
        samples_out.x.y.z["label"].append(sample_in.z.y.x.label.numpy() * mul)


@hub.compute
def fn5(sample_in, samples_out, mul=1, copy=1):
    for _ in range(copy):
        samples_out.append(
            {
                "image": sample_in.image.numpy() * mul,
                "label": sample_in.label.numpy() * mul,
            }
        )


@hub.compute
def read_image(sample_in, samples_out):
    samples_out.image.append(hub.read(sample_in))


@hub.compute
def crop_image(sample_in, samples_out, copy=1):
    for _ in range(copy):
        samples_out.image.append(sample_in.image.numpy()[:100, :100, :])


@hub.compute
def filter_tr(sample_in, sample_out):
    if sample_in % 2 == 0:
        sample_out.image.append(sample_in * np.ones((100, 100)))


@hub.compute
def inplace_transform(sample_in, samples_out):
    samples_out.img.append(2 * sample_in.img.numpy())
    samples_out.img.append(3 * sample_in.img.numpy())
    samples_out.label.append(2 * sample_in.label.numpy())
    samples_out.label.append(3 * sample_in.label.numpy())


def check_target_array(ds, index, target):
    np.testing.assert_array_equal(
        ds.img[index].numpy(), target * np.ones((500, 500, 3))
    )
    np.testing.assert_array_equal(
        ds.label[index].numpy(), target * np.ones((100, 100, 3))
    )


@all_schedulers
@enabled_non_gcs_datasets
def test_single_transform_hub_dataset(ds, scheduler):
    data_in = hub.dataset("./test/single_transform_hub_dataset", overwrite=True)
    with data_in:
        data_in.create_tensor("image")
        data_in.create_tensor("label")
        for i in range(1, 100):
            data_in.image.append(i * np.ones((i, i)))
            data_in.label.append(i * np.ones((1,)))
    ds_out = ds
    ds_out.create_tensor("image")
    ds_out.create_tensor("label")
    if (
        isinstance(remove_memory_cache(ds.storage), MemoryProvider)
        and scheduler != "threaded"
    ):
        # any scheduler other than `threaded` will not work with a dataset stored in memory
        with pytest.raises(InvalidOutputDatasetError):
            fn2(copy=1, mul=2).eval(
                data_in,
                ds_out,
                num_workers=TRANSFORM_TEST_NUM_WORKERS,
                scheduler=scheduler,
            )
        data_in.delete()
        return

    fn2(copy=1, mul=2).eval(
        data_in, ds_out, num_workers=TRANSFORM_TEST_NUM_WORKERS, scheduler=scheduler
    )
    assert len(ds_out) == 99
    for index in range(1, 100):
        np.testing.assert_array_equal(
            ds_out[index - 1].image.numpy(), 2 * index * np.ones((index, index))
        )
        np.testing.assert_array_equal(
            ds_out[index - 1].label.numpy(), 2 * index * np.ones((1,))
        )

    assert ds_out.image.shape_interval.lower == (99, 1, 1)
    assert ds_out.image.shape_interval.upper == (99, 99, 99)
    data_in.delete()


@enabled_datasets
def test_groups(ds):
    with CliRunner().isolated_filesystem():
        with hub.dataset("./test/transform_hub_in_generic") as data_in:
            data_in.create_tensor("data/image")
            data_in.create_tensor("data/label")
            for i in range(1, 100):
                data_in.data.image.append(i * np.ones((i, i)))
                data_in.data.label.append(i * np.ones((1,)))
        data_in = hub.dataset("./test/transform_hub_in_generic")
        ds_out = ds
        ds_out.create_tensor("stuff/image")
        ds_out.create_tensor("stuff/label")

        data_in = data_in.data
        ds_out = ds_out.stuff

        fn2(copy=1, mul=2).eval(data_in, ds_out, num_workers=TRANSFORM_TEST_NUM_WORKERS)
        assert len(ds_out) == 99
        for index in range(1, 100):
            np.testing.assert_array_equal(
                ds_out[index - 1].image.numpy(), 2 * index * np.ones((index, index))
            )
            np.testing.assert_array_equal(
                ds_out[index - 1].label.numpy(), 2 * index * np.ones((1,))
            )

        assert ds_out.image.shape_interval.lower == (99, 1, 1)
        assert ds_out.image.shape_interval.upper == (99, 99, 99)


@enabled_datasets
def test_groups_2(ds):
    with CliRunner().isolated_filesystem():
        with hub.dataset("./test/transform_hub_in_generic") as data_in:
            data_in.create_tensor("data/z/y/x/image")
            data_in.create_tensor("data/z/y/x/label")
            for i in range(1, 100):
                data_in.data.z.y.x.image.append(i * np.ones((i, i)))
                data_in.data.z.y.x.label.append(i * np.ones((1,)))
        data_in = hub.dataset("./test/transform_hub_in_generic")
        ds_out = ds
        ds_out.create_tensor("stuff/x/y/z/image")
        ds_out.create_tensor("stuff/x/y/z/label")

        data_in = data_in.data
        ds_out = ds_out.stuff

        fn5(copy=1, mul=2).eval(data_in, ds_out, num_workers=TRANSFORM_TEST_NUM_WORKERS)
        assert len(ds_out) == 99
        for index in range(1, 100):
            np.testing.assert_array_equal(
                ds_out.x.y.z.image[index - 1].numpy(),
                2 * index * np.ones((index, index)),
            )
            np.testing.assert_array_equal(
                ds_out.x.y.z.label[index - 1].numpy(), 2 * index * np.ones((1,))
            )

        assert ds_out.x.y.z.image.shape_interval.lower == (99, 1, 1)
        assert ds_out.x.y.z.image.shape_interval.upper == (99, 99, 99)


@enabled_non_gcs_datasets
@parametrize_num_workers
@all_schedulers
def test_single_transform_hub_dataset_htypes(ds, num_workers, scheduler):
    data_in = hub.dataset("./test/single_transform_hub_dataset_htypes", overwrite=True)
    with data_in:
        data_in.create_tensor("image", htype="image", sample_compression="png")
        data_in.create_tensor("label", htype="class_label")
        for i in range(1, 100):
            data_in.image.append(i * np.ones((i, i), dtype="uint8"))
            data_in.label.append(i * np.ones((1,), dtype="uint32"))
    ds_out = ds
    ds_out.create_tensor("image")
    ds_out.create_tensor("label")
    if (
        isinstance(remove_memory_cache(ds.storage), MemoryProvider)
        and scheduler != "threaded"
        and num_workers > 0
    ):
        # any scheduler other than `threaded` will not work with a dataset stored in memory
        # num_workers = 0 automatically does single threaded irrespective of the scheduler
        with pytest.raises(InvalidOutputDatasetError):
            fn2(copy=1, mul=2).eval(
                data_in, ds_out, num_workers=num_workers, scheduler=scheduler
            )
        data_in.delete()
        return
    fn2(copy=1, mul=2).eval(
        data_in, ds_out, num_workers=num_workers, scheduler=scheduler
    )
    assert len(ds_out) == 99
    for index in range(1, 100):
        np.testing.assert_array_equal(
            ds_out[index - 1].image.numpy(), 2 * index * np.ones((index, index))
        )
        np.testing.assert_array_equal(
            ds_out[index - 1].label.numpy(), 2 * index * np.ones((1,))
        )

    assert ds_out.image.shape_interval.lower == (99, 1, 1)
    assert ds_out.image.shape_interval.upper == (99, 99, 99)
    data_in.delete()


@all_schedulers
@enabled_non_gcs_datasets
def test_chain_transform_list_small(ds, scheduler):
    ls = [i for i in range(100)]
    ds_out = ds
    ds_out.create_tensor("image")
    ds_out.create_tensor("label")
    pipeline = hub.compose([fn1(mul=5, copy=2), fn2(mul=3, copy=3)])
    if (
        isinstance(remove_memory_cache(ds.storage), MemoryProvider)
        and scheduler != "threaded"
    ):
        # any scheduler other than `threaded` will not work with a dataset stored in memory
        with pytest.raises(InvalidOutputDatasetError):
            pipeline.eval(
                ls, ds_out, num_workers=TRANSFORM_TEST_NUM_WORKERS, scheduler=scheduler
            )
        return
    pipeline.eval(
        ls, ds_out, num_workers=TRANSFORM_TEST_NUM_WORKERS, scheduler=scheduler
    )
    assert len(ds_out) == 600
    for i in range(100):
        for index in range(6 * i, 6 * i + 6):
            np.testing.assert_array_equal(
                ds_out[index].image.numpy(), 15 * i * np.ones((337, 200))
            )
            np.testing.assert_array_equal(
                ds_out[index].label.numpy(), 15 * i * np.ones((1,))
            )


@all_schedulers
@enabled_non_gcs_datasets
@pytest.mark.xfail(raises=TransformError, strict=False)
def test_chain_transform_list_big(ds, scheduler):
    ls = [i for i in range(2)]
    ds_out = ds
    ds_out.create_tensor("image")
    ds_out.create_tensor("label")
    pipeline = hub.compose([fn3(mul=5, copy=2), fn2(mul=3, copy=3)])
    if (
        isinstance(remove_memory_cache(ds.storage), MemoryProvider)
        and scheduler != "threaded"
    ):
        # any scheduler other than `threaded` will not work with a dataset stored in memory
        with pytest.raises(InvalidOutputDatasetError):
            pipeline.eval(
                ls, ds_out, num_workers=TRANSFORM_TEST_NUM_WORKERS, scheduler=scheduler
            )
        return
    pipeline.eval(
        ls, ds_out, num_workers=TRANSFORM_TEST_NUM_WORKERS, scheduler=scheduler
    )
    assert len(ds_out) == 12
    for i in range(2):
        for index in range(6 * i, 6 * i + 6):
            np.testing.assert_array_equal(
                ds_out[index].image.numpy(), 15 * i * np.ones((1310, 2087))
            )
            np.testing.assert_array_equal(
                ds_out[index].label.numpy(), 15 * i * np.ones((13,))
            )


@all_schedulers
@all_compressions
@enabled_non_gcs_datasets
def test_transform_hub_read(ds, cat_path, sample_compression, scheduler):
    data_in = [cat_path] * 10
    ds_out = ds
    ds_out.create_tensor("image", htype="image", sample_compression=sample_compression)

    if (
        isinstance(remove_memory_cache(ds.storage), MemoryProvider)
        and scheduler != "threaded"
    ):
        # any scheduler other than `threaded` will not work with a dataset stored in memory
        with pytest.raises(InvalidOutputDatasetError):
            read_image().eval(
                data_in,
                ds_out,
                num_workers=TRANSFORM_TEST_NUM_WORKERS,
                scheduler=scheduler,
            )
        return

    read_image().eval(
        data_in, ds_out, num_workers=TRANSFORM_TEST_NUM_WORKERS, scheduler=scheduler
    )
    assert len(ds_out) == 10
    for i in range(10):
        assert ds_out.image[i].numpy().shape == (900, 900, 3)
        np.testing.assert_array_equal(ds_out.image[i].numpy(), ds_out.image[0].numpy())


@all_schedulers
@all_compressions
@enabled_non_gcs_datasets
def test_transform_hub_read_pipeline(ds, cat_path, sample_compression, scheduler):
    data_in = [cat_path] * 10
    ds_out = ds
    ds_out.create_tensor("image", htype="image", sample_compression=sample_compression)
    pipeline = hub.compose([read_image(), crop_image(copy=2)])
    if (
        isinstance(remove_memory_cache(ds.storage), MemoryProvider)
        and scheduler != "threaded"
    ):
        # any scheduler other than `threaded` will not work with a dataset stored in memory
        with pytest.raises(InvalidOutputDatasetError):
            pipeline.eval(
                data_in,
                ds_out,
                num_workers=TRANSFORM_TEST_NUM_WORKERS,
                scheduler=scheduler,
            )
        return
    pipeline.eval(
        data_in, ds_out, num_workers=TRANSFORM_TEST_NUM_WORKERS, scheduler=scheduler
    )
    assert len(ds_out) == 20
    for i in range(20):
        assert ds_out.image[i].numpy().shape == (100, 100, 3)
        np.testing.assert_array_equal(ds_out.image[i].numpy(), ds_out.image[0].numpy())


@enabled_non_gcs_datasets
def test_hub_like(ds, scheduler="threaded"):
    with CliRunner().isolated_filesystem():
        data_in = ds
        with data_in:
            data_in.create_tensor("image", htype="image", sample_compression="png")
            data_in.create_tensor("label", htype="class_label")
            for i in range(1, 100):
                data_in.image.append(i * np.ones((i, i), dtype="uint8"))
                data_in.label.append(i * np.ones((1,), dtype="uint32"))
        ds_out = hub.like("./transform_hub_like", data_in)
        if (
            isinstance(remove_memory_cache(ds.storage), MemoryProvider)
            and scheduler != "threaded"
        ):
            # any scheduler other than `threaded` will not work with a dataset stored in memory
            with pytest.raises(InvalidOutputDatasetError):
                fn2(copy=1, mul=2).eval(
                    data_in,
                    ds_out,
                    num_workers=TRANSFORM_TEST_NUM_WORKERS,
                    scheduler=scheduler,
                )
            return
        fn2(copy=1, mul=2).eval(
            data_in, ds_out, num_workers=TRANSFORM_TEST_NUM_WORKERS, scheduler=scheduler
        )
        assert len(ds_out) == 99
        for index in range(1, 100):
            np.testing.assert_array_equal(
                ds_out[index - 1].image.numpy(), 2 * index * np.ones((index, index))
            )
            np.testing.assert_array_equal(
                ds_out[index - 1].label.numpy(), 2 * index * np.ones((1,))
            )

        assert ds_out.image.shape_interval.lower == (99, 1, 1)
        assert ds_out.image.shape_interval.upper == (99, 99, 99)


def test_transform_empty(local_ds):
    local_ds.create_tensor("image")

    ls = list(range(10))
    filter_tr().eval(ls, local_ds)

    assert len(local_ds) == 5

    for i in range(5):
        np.testing.assert_array_equal(
            local_ds[i].image.numpy(), 2 * i * np.ones((100, 100))
        )


def test_pbar_description():
    assert get_pbar_description([fn1()]) == "Evaluating fn1"
    assert get_pbar_description([fn1(), fn2()]) == "Evaluating [fn1, fn2]"
    assert get_pbar_description([fn1(), fn1()]) == "Evaluating [fn1, fn1]"
    assert (
        get_pbar_description([fn1(), fn1(), read_image()])
        == "Evaluating [fn1, fn1, read_image]"
    )


def test_bad_transform(memory_ds):
    ds = memory_ds
    ds.create_tensor("x")
    ds.create_tensor("y")
    with ds:
        ds.x.extend(np.random.rand(10, 1))
        ds.y.extend(np.random.rand(10, 1))
    ds2 = hub.like("mem://dummy2", ds)

    @hub.compute
    def fn_filter(sample_in, sample_out):
        sample_out.y.append(sample_in.y.numpy())
        return sample_out

    with pytest.raises(TransformError):
        fn_filter().eval(ds, ds2, progressbar=True)


def test_transform_persistance(local_ds_generator, num_workers=2, scheduler="threaded"):
    data_in = hub.dataset("./test/single_transform_hub_dataset_htypes", overwrite=True)
    with data_in:
        data_in.create_tensor("image", htype="image", sample_compression="png")
        data_in.create_tensor("label", htype="class_label")
        for i in range(1, 100):
            data_in.image.append(i * np.ones((i, i), dtype="uint8"))
            data_in.label.append(i * np.ones((1,), dtype="uint32"))
    ds_out = local_ds_generator()
    ds_out.create_tensor("image")
    ds_out.create_tensor("label")
    if (
        isinstance(remove_memory_cache(ds_out.storage), MemoryProvider)
        and scheduler != "threaded"
        and num_workers > 0
    ):
        # any scheduler other than `threaded` will not work with a dataset stored in memory
        # num_workers = 0 automatically does single threaded irrespective of the scheduler
        with pytest.raises(InvalidOutputDatasetError):
            fn2(copy=1, mul=2).eval(
                data_in, ds_out, num_workers=num_workers, scheduler=scheduler
            )
        data_in.delete()
        return
    fn2(copy=1, mul=2).eval(
        data_in, ds_out, num_workers=num_workers, scheduler=scheduler
    )

    def test_ds_out():
        assert len(ds_out) == 99
        for index in range(1, 100):
            np.testing.assert_array_equal(
                ds_out[index - 1].image.numpy(), 2 * index * np.ones((index, index))
            )
            np.testing.assert_array_equal(
                ds_out[index - 1].label.numpy(), 2 * index * np.ones((1,))
            )

        assert ds_out.image.shape_interval.lower == (99, 1, 1)
        assert ds_out.image.shape_interval.upper == (99, 99, 99)

    test_ds_out()
    ds_out = local_ds_generator()
    test_ds_out()

    data_in.delete()


def test_ds_append_in_transform(memory_ds):
    ds = memory_ds
    data_in = hub.dataset("./test/single_transform_hub_dataset", overwrite=True)
    with data_in:
        data_in.create_tensor("image")
        data_in.create_tensor("label")
        for i in range(1, 100):
            data_in.image.append(i * np.ones((i, i)))
            data_in.label.append(i * np.ones((1,)))
    ds_out = ds
    ds_out.create_tensor("image")
    ds_out.create_tensor("label")

    fn5(copy=1, mul=2).eval(
        data_in, ds_out, num_workers=2, scheduler="threaded", progressbar=False
    )
    assert len(ds_out) == 99
    for index in range(1, 100):
        np.testing.assert_array_equal(
            ds_out[index - 1].image.numpy(), 2 * index * np.ones((index, index))
        )
        np.testing.assert_array_equal(
            ds_out[index - 1].label.numpy(), 2 * index * np.ones((1,))
        )

    assert ds_out.image.shape_interval.lower == (99, 1, 1)
    assert ds_out.image.shape_interval.upper == (99, 99, 99)
    data_in.delete()


def test_transform_pass_through():
    data_in = hub.dataset("mem://ds1")
    data_in.create_tensor("image", htype="image", sample_compression="png")
    data_in.create_tensor("label", htype="class_label")
    for i in range(1, 100):
        data_in.image.append(i * np.ones((i, i), dtype="uint8"))
        data_in.label.append(i * np.ones((1,), dtype="uint32"))
    ds_out = hub.dataset("mem://ds2")
    ds_out.create_tensor("image", htype="image", sample_compression="png")
    ds_out.create_tensor("label", htype="class_label")
    fn4().eval(data_in, ds_out, num_workers=2, scheduler="threaded", progressbar=False)
    for i in range(len(data_in)):
        np.testing.assert_array_equal(
            data_in[i].image.numpy(), ds_out[i * 2].image.numpy()
        )
        np.testing.assert_array_equal(
            data_in[i].label.numpy(), ds_out[i * 2].label.numpy()
        )
        np.testing.assert_array_equal(
            data_in[i].image.numpy() * 2, ds_out[i * 2 + 1].image.numpy()
        )
        np.testing.assert_array_equal(
            data_in[i].label.numpy() * 2, ds_out[i * 2 + 1].label.numpy()
        )


def test_inplace_transform(local_ds_generator):
    ds = local_ds_generator()

    with ds:
        ds.create_tensor("img")
        ds.create_tensor("label")
        for _ in range(100):
            ds.img.append(np.ones((500, 500, 3)))
            ds.label.append(np.ones((100, 100, 3)))
        a = ds.commit()
        assert len(ds) == 100
        for i in range(100):
            check_target_array(ds, i, 1)

        inplace_transform().eval(ds, num_workers=TRANSFORM_TEST_NUM_WORKERS)
        assert ds.img.chunk_engine.num_samples == len(ds) == 200

        for i in range(200):
            target = 2 if i % 2 == 0 else 3
            check_target_array(ds, i, target)

        ds.checkout(a)
        assert len(ds) == 100
        for i in range(100):
            check_target_array(ds, i, 1)

    ds = local_ds_generator()
    assert len(ds) == 200
    for i in range(200):
        target = 2 if i % 2 == 0 else 3
        check_target_array(ds, i, target)

    ds.checkout(a)
    assert len(ds) == 100
    for i in range(100):
        check_target_array(ds, i, 1)


def test_inplace_transform_without_commit(local_ds_generator):
    ds = local_ds_generator()

    with ds:
        ds.create_tensor("img")
        ds.create_tensor("label")
        for _ in range(100):
            ds.img.append(np.ones((500, 500, 3)))
            ds.label.append(np.ones((100, 100, 3)))
        assert len(ds) == 100
        for i in range(100):
            check_target_array(ds, i, 1)

        inplace_transform().eval(ds, num_workers=TRANSFORM_TEST_NUM_WORKERS)
        assert ds.img.chunk_engine.num_samples == len(ds) == 200

        for i in range(200):
            target = 2 if i % 2 == 0 else 3
            check_target_array(ds, i, target)

    ds = local_ds_generator()
    assert len(ds) == 200
    for i in range(200):
        target = 2 if i % 2 == 0 else 3
        check_target_array(ds, i, target)


def test_inplace_transform_non_head(local_ds_generator):
    ds = local_ds_generator()
    with ds:
        ds.create_tensor("img")
        ds.create_tensor("label")
        for _ in range(100):
            ds.img.append(np.ones((500, 500, 3)))
            ds.label.append(np.ones((100, 100, 3)))
        assert len(ds) == 100
        for i in range(100):
            check_target_array(ds, i, 1)
        a = ds.commit()
        for _ in range(50):
            ds.img.append(np.ones((500, 500, 3)))
            ds.label.append(np.ones((100, 100, 3)))
        assert len(ds) == 150
        for i in range(150):
            check_target_array(ds, i, 1)

        ds.checkout(a)

        # transforming non-head node
        inplace_transform().eval(ds, num_workers=4)
        b = ds.commit_id

        assert len(ds) == 200
        for i in range(200):
            target = 2 if i % 2 == 0 else 3
            check_target_array(ds, i, target)

        ds.checkout(a)
        assert len(ds) == 100
        for i in range(100):
            check_target_array(ds, i, 1)

        ds.checkout("main")
        assert len(ds) == 150
        for i in range(150):
            check_target_array(ds, i, 1)

    ds = local_ds_generator()
    assert len(ds) == 150
    for i in range(150):
        check_target_array(ds, i, 1)

    ds.checkout(a)
    assert len(ds) == 100
    for i in range(100):
        check_target_array(ds, i, 1)

    ds.checkout(b)
    assert len(ds) == 200
    for i in range(200):
        target = 2 if i % 2 == 0 else 3
        check_target_array(ds, i, target)

# Copyright 2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License").
# You may not use this file except in compliance with the License.
# A copy of the License is located at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# or in the "license" file accompanying this file. This file is distributed
# on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either
# express or implied. See the License for the specific language governing
# permissions and limitations under the License.
import logging
from typing import Optional, List, Dict, Any

import benchmarking
from benchmarking.commons.baselines import MethodDefinitions
from benchmarking.commons.hpo_main_common import (
    parse_args as _parse_args,
    ExtraArgsType,
    MapExtraArgsType,
    PostProcessingType,
)
from benchmarking.commons.hpo_main_local import (
    RealBenchmarkDefinitions,
    get_benchmark,
    create_objects_for_tuner,
)
from benchmarking.commons.launch_remote_common import sagemaker_estimator_args
from benchmarking.commons.utils import (
    get_master_random_seed,
)
from syne_tune.backend import SageMakerBackend
from syne_tune.remote.estimators import sagemaker_estimator
from syne_tune.backend.sagemaker_backend.sagemaker_utils import (
    default_sagemaker_session,
)
from syne_tune.tuner import Tuner


# SageMaker managed warm pools:
# https://docs.aws.amazon.com/sagemaker/latest/dg/train-warm-pools.html#train-warm-pools-resource-limits
# Maximum time a warm pool instance is kept alive, waiting to be associated with
# a new job. Setting this too large may lead to extra costs.
WARM_POOL_KEEP_ALIVE_PERIOD_IN_SECONDS = 10 * 60


def parse_args(
    methods: Dict[str, Any], extra_args: Optional[ExtraArgsType] = None
) -> (Any, List[str], List[int]):
    """Parse command line arguments for SageMaker backend experiments.

    :param methods: If ``--method`` is not given, then ``method_names`` are the
        keys of this dictionary
    :param extra_args: List of dictionaries, containing additional arguments
        to be passed. Must contain ``name`` for argument name (without leading
        ``"--"``), and other kwargs to ``parser.add_argument``. Optional
    :return: ``(args, method_names, seeds)``, where ``args`` is result of
        ``parser.parse_args()``, ``method_names`` see ``methods``, and
        ``seeds`` are list of seeds specified by ``--num_seeds`` and ``--start_seed``
    """
    if extra_args is None:
        extra_args = []
    else:
        extra_args = extra_args.copy()
    extra_args.extend(
        [
            dict(
                name="benchmark",
                type=str,
                default="resnet_cifar10",
                help="Benchmark to run",
            ),
            dict(
                name="max_failures",
                type=int,
                default=3,
                help=(
                    "Number of trials which can fail without experiment being "
                    "terminated"
                ),
            ),
            dict(
                name="warm_pool",
                type=int,
                default=0,
                help=(
                    "If 1, the SageMaker managed warm pools feature is used. "
                    "This reduces startup delays, leading to an experiment "
                    "finishing in less time."
                ),
            ),
            dict(
                name="instance_type",
                type=str,
                help="AWS SageMaker instance type (overwrites default of benchmark)",
            ),
            dict(
                name="start_jobs_without_delay",
                type=int,
                default=0,
                help=(
                    "If 1, the tuner starts new trials immediately after "
                    "sending existing ones a stop signal. This leads to more "
                    "than n_workers instances being used during certain times, "
                    "which can lead to quotas being exceeded, or the warm pool "
                    "feature not working optimal."
                ),
            ),
            dict(
                name="delete_checkpoints",
                type=int,
                default=1,
                help=(
                    "If 1, checkpoints files on S3 are removed at the end "
                    "of the experiment."
                ),
            ),
        ]
    )
    args, method_names, seeds = _parse_args(methods, extra_args)
    args.warm_pool = bool(args.warm_pool)
    args.start_jobs_without_delay = bool(args.start_jobs_without_delay)
    args.delete_checkpoints = bool(args.delete_checkpoints)
    return args, method_names, seeds


def main(
    methods: MethodDefinitions,
    benchmark_definitions: RealBenchmarkDefinitions,
    extra_args: Optional[ExtraArgsType] = None,
    map_extra_args: Optional[MapExtraArgsType] = None,
    post_processing: Optional[PostProcessingType] = None,
):
    """
    Runs experiment with SageMaker backend.

    Command line arguments must specify a single benchmark, method, and seed,
    for example ``--method ASHA --num_seeds 5 --start_seed 4`` starts experiment
    with ``seed=4``, or ``--method ASHA --num_seeds 1`` starts experiment with
    ``seed=0``. Here, ``ASHA`` must be key in ``methods``.

    :param methods: Dictionary with method constructors
    :param benchmark_definitions: Definitions of benchmark; one is selected from
        command line arguments
    :param extra_args: Extra arguments for command line parser. Optional
    :param map_extra_args: Maps ``args`` returned by :func:`parse_args` to dictionary
        for extra argument values. Needed if ``extra_args`` is given
    :param post_processing: Called after tuning has finished, passing the tuner
        as argument. Can be used for postprocessing, such as output or storage
        of extra information
    """
    args, method_names, seeds = parse_args(methods, extra_args)
    experiment_tag = args.experiment_tag
    benchmark_name = args.benchmark
    master_random_seed = get_master_random_seed(args.random_seed)
    assert (
        len(method_names) == 1 and len(seeds) == 1
    ), "Can only launch single (method, seed). Use launch_remote to launch several combinations"
    method = method_names[0]
    seed = seeds[0]
    logging.getLogger().setLevel(logging.INFO)

    benchmark = get_benchmark(args, benchmark_definitions, sagemaker_backend=True)
    print(f"Starting experiment ({method}/{benchmark_name}/{seed}) of {experiment_tag}")

    sm_args = sagemaker_estimator_args(
        entry_point=benchmark.script,
        experiment_tag="A",
        tuner_name="B",
        benchmark=benchmark,
    )
    del sm_args["checkpoint_s3_uri"]
    sm_args["sagemaker_session"] = default_sagemaker_session()
    sm_args["dependencies"] = benchmarking.__path__
    if args.warm_pool:
        print(
            "--------------------------------------------------------------------------\n"
            "Using SageMaker managed warm pools in order to decrease start-up delays.\n"
            f"In order for this to work, you need to have at least {benchmark.n_workers} quotas of the type\n"
            f"   {benchmark.instance_type} for training warm pool usage\n"
            "--------------------------------------------------------------------------"
        )
        sm_args["keep_alive_period_in_seconds"] = WARM_POOL_KEEP_ALIVE_PERIOD_IN_SECONDS
    if args.instance_type is not None:
        sm_args["instance_type"] = args.instance_type
    trial_backend = SageMakerBackend(
        sm_estimator=sagemaker_estimator[benchmark.framework](**sm_args),
        # names of metrics to track. Each metric will be detected by Sagemaker if it is written in the
        # following form: "[RMSE]: 1.2", see in train_main_example how metrics are logged for an example
        delete_checkpoints=args.delete_checkpoints,
        metrics_names=[benchmark.metric],
    )

    tuner_kwargs = create_objects_for_tuner(
        args,
        methods=methods,
        extra_args=extra_args,
        map_extra_args=map_extra_args,
        method=method,
        benchmark=benchmark,
        master_random_seed=master_random_seed,
        seed=seed,
        verbose=True,
    )
    tuner = Tuner(
        trial_backend=trial_backend,
        **tuner_kwargs,
        sleep_time=5.0,
        max_failures=args.max_failures,
        start_jobs_without_delay=args.start_jobs_without_delay,
    )
    tuner.run()
    if post_processing is not None:
        post_processing(tuner)

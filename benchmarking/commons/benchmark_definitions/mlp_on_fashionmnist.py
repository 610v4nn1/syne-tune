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
from pathlib import Path

from benchmarking.commons.benchmark_definitions.common import RealBenchmarkDefinition
from benchmarking.definitions.definition_mlp_on_fashion_mnist import (
    mlp_fashionmnist_default_params,
    mlp_fashionmnist_benchmark as _mlp_fashionmnist_benchmark,
)


# Note: Latest PyTorch version 1.10 not yet supported with remote launching
def mlp_fashionmnist_benchmark(sagemaker_backend: bool = False, **kwargs):
    params = {"backend": "sagemaker"} if sagemaker_backend else None
    params = mlp_fashionmnist_default_params(params)
    benchmark = _mlp_fashionmnist_benchmark(params)
    _kwargs = dict(
        script=Path(benchmark["script"]),
        config_space=benchmark["config_space"],
        max_wallclock_time=3 * 3600,  # TODO
        n_workers=params["num_workers"],
        instance_type=params["instance_type"],
        metric=benchmark["metric"],
        mode=benchmark["mode"],
        max_resource_attr=benchmark["max_resource_attr"],
        resource_attr=benchmark["resource_attr"],
        framework="PyTorch",
        estimator_kwargs=dict(
            framework_version="1.7.1",
            py_version="py3",
        ),
    )
    _kwargs.update(kwargs)
    return RealBenchmarkDefinition(**_kwargs)

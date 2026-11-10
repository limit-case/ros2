// Copyright 2025 Yajan
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

#pragma once
#include <vector>

namespace limit_case_ros2
{

/// Priority-Flood depression filling (Barnes, Lehman, Mulla 2014, "improved" variant).
/// `elev` is row-major w*h. `fill` gets the filled surface: fill >= elev everywhere,
/// border cells are never raised. 4-connectivity. +inf cells act as walls.
void priorityFlood(const std::vector<float> & elev, int w, int h, std::vector<float> & fill);

}  // namespace limit_case_ros2

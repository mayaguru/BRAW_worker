#pragma once

#include <filesystem>

#include "core/frame_buffer.h"

namespace braw {

// Writes a quick PPM file for validation. The format is simple ASCII and lets us
// verify the decode path before integrating PNG/TinyEXR in later steps.
bool write_ppm(const std::filesystem::path& output_path, const FrameBuffer& buffer);

}  // namespace braw

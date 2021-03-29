/*

Copyright (c) 2015, 2017, 2019-2020, Arvid Norberg
All rights reserved.

You may use, distribute and modify this code under the terms of the BSD license,
see LICENSE file.
*/

#ifndef TEST_UTILS_HPP
#define TEST_UTILS_HPP

#include <string>

#include "test.hpp"
#include "libtorrent/time.hpp"
#include "libtorrent/download_priority.hpp"
#include "libtorrent/fwd.hpp"

#include "libtorrent/sha1_hash.hpp"
#include "libtorrent/aux_/vector.hpp"
#include "libtorrent/aux_/path.hpp"
#include <vector>
#include <fstream>

namespace libtorrent
{
	EXPORT std::string time_now_string();
	EXPORT std::string time_to_string(lt::time_point const tp);
}

constexpr inline lt::download_priority_t operator "" _pri(unsigned long long const p)
{ return lt::download_priority_t(static_cast<std::uint8_t>(p)); }

constexpr inline lt::file_index_t operator "" _file(unsigned long long const p)
{ return lt::file_index_t(static_cast<int>(p)); }

constexpr inline lt::piece_index_t operator "" _piece(unsigned long long const p)
{ return lt::piece_index_t(static_cast<int>(p)); }

EXPORT std::vector<char> serialize(lt::torrent_info const& ti);

EXPORT lt::aux::vector<lt::sha256_hash> build_tree(int const size);

#ifdef _WIN32
int EXPORT truncate(char const* file, std::int64_t size);
#endif

struct EXPORT ofstream : std::ofstream
{
	ofstream(char const* filename);
};

EXPORT bool exists(std::string const& f);

#endif


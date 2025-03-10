#!/usr/bin/env python3
# vim: tabstop=8 expandtab shiftwidth=4 softtabstop=4


import libtorrent as lt

import unittest
import time
import datetime
import os
import shutil
import binascii
import subprocess as sub
import sys
import pickle
import threading
import tempfile
import socket
import select

import dummy_data

# include terminal interface for travis parallel executions of scripts which use
# terminal features: fix multiple stdin assignment at termios.tcgetattr
if os.name != 'nt':
    import pty

settings = {
    'alert_mask': lt.alert.category_t.all_categories,
    'enable_dht': False, 'enable_lsd': False, 'enable_natpmp': False,
    'enable_upnp': False, 'listen_interfaces': '0.0.0.0:0', 'file_pool_size': 1}


def has_deprecated():
    return hasattr(lt, 'version')


class test_create_torrent(unittest.TestCase):

    def test_from_torrent_info(self):
        ti = lt.torrent_info('unordered.torrent')
        print(ti.ssl_cert())
        ct = lt.create_torrent(ti)
        entry = ct.generate()
        content = lt.bencode(entry).strip()
        with open('unordered.torrent', 'rb') as f:
            file_content = bytearray(f.read().strip())
            print(content)
            print(file_content)
            print(entry)
            self.assertEqual(content, file_content)

    def test_from_scratch(self):
        fs = lt.file_storage()
        fs.add_file('test/file1', 1000)
        fs.add_file('test/file2', 2000)
        self.assertEqual(fs.file_name(0), 'file1')
        self.assertEqual(fs.file_name(1), 'file2')
        ct = lt.create_torrent(fs)
        ct.add_url_seed('foo')
        ct.add_http_seed('bar')
        ct.add_tracker('bar')
        ct.set_root_cert('1234567890')
        ct.add_collection('1337')
        for i in range(ct.num_pieces()):
            ct.set_hash(i, b'abababababababababab')
        entry = ct.generate()
        encoded = lt.bencode(entry)
        print(encoded)

        # zero out the creation date:
        encoded = encoded.split(b'13:creation datei', 1)
        encoded[1] = b'0e' + encoded[1].split(b'e', 1)[1]
        encoded = b'13:creation datei'.join(encoded)

        self.assertEqual(encoded, b'd8:announce3:bar13:creation datei0e9:httpseeds3:bar4:infod11:collectionsl4:1337e5:filesld6:lengthi1000e4:pathl5:file1eed4:attr1:p6:lengthi15384e4:pathl4:.pad5:15384eed6:lengthi2000e4:pathl5:file2eee4:name4:test12:piece lengthi16384e6:pieces40:abababababababababababababababababababab8:ssl-cert10:1234567890e8:url-list3:fooe')


class test_session_stats(unittest.TestCase):

    def test_add_torrent_params(self):
        atp = lt.add_torrent_params()

        for field_name in dir(atp):
            field = getattr(atp, field_name)
            print(field_name, field)

        atp.renamed_files = {}
        atp.merkle_tree = []
        atp.unfinished_pieces = {}
        atp.have_pieces = []
        atp.banned_peers = []
        atp.verified_pieces = []
        atp.piece_priorities = []
        atp.url_seeds = []

    def test_unique(self):
        metrics = lt.session_stats_metrics()
        self.assertTrue(len(metrics) > 40)
        idx = set()
        for m in metrics:
            self.assertTrue(m.value_index not in idx)
            idx.add(m.value_index)

    def test_find_idx(self):
        self.assertEqual(lt.find_metric_idx("peer.error_peers"), 0)


class test_torrent_handle(unittest.TestCase):

    def setup(self):
        self.ses = lt.session(settings)
        self.ti = lt.torrent_info('url_seed_multi.torrent')
        self.h = self.ses.add_torrent({
            'ti': self.ti, 'save_path': os.getcwd(),
            'flags': lt.torrent_flags.default_flags})

    def test_add_torrent_error(self):
        self.ses = lt.session(settings)
        self.ti = lt.torrent_info('url_seed_multi.torrent')
        with self.assertRaises(RuntimeError):
            self.ses.add_torrent({'ti': self.ti, 'save_path': os.getcwd(), 'info_hashes': b'abababababababababab'})

    def test_move_storage(self):
        self.setup()
        self.h.move_storage(u'test-dir')
        self.h.move_storage(b'test-dir2')
        self.h.move_storage('test-dir3')
        self.h.move_storage(u'test-dir', flags=lt.move_flags_t.dont_replace)
        self.h.move_storage(u'test-dir', flags=2)
        self.h.move_storage(b'test-dir2', flags=2)
        self.h.move_storage('test-dir3', flags=2)

    def test_torrent_handle(self):
        self.setup()
        self.assertEqual(self.h.get_file_priorities(), [4, 4])
        self.assertEqual(self.h.get_piece_priorities(), [4])

        self.h.prioritize_files([0, 1])
        # workaround for asynchronous priority update
        time.sleep(1)
        self.assertEqual(self.h.get_file_priorities(), [0, 1])

        self.h.prioritize_pieces([0])
        self.assertEqual(self.h.get_piece_priorities(), [0])

        # also test the overload that takes a list of piece->priority mappings
        self.h.prioritize_pieces([(0, 1)])
        self.assertEqual(self.h.get_piece_priorities(), [1])
        self.h.connect_peer(('127.0.0.1', 6881))
        self.h.connect_peer(('127.0.0.2', 6881), source=4)
        self.h.connect_peer(('127.0.0.3', 6881), flags=2)
        self.h.connect_peer(('127.0.0.4', 6881), flags=2, source=4)

        torrent_files = self.h.torrent_file()
        print(torrent_files.map_file(0, 0, 0).piece)

        print(self.h.queue_position())

    def test_torrent_handle_in_set(self):
        self.setup()
        torrents = set()
        torrents.add(self.h)

        # get another instance of a torrent_handle that represents the same
        # torrent. Make sure that when we add it to a set, it just replaces the
        # existing object
        t = self.ses.get_torrents()
        self.assertEqual(len(t), 1)
        for h in t:
            torrents.add(h)

        self.assertEqual(len(torrents), 1)

    def test_torrent_handle_in_dict(self):
        self.setup()
        torrents = {}
        torrents[self.h] = 'foo'

        # get another instance of a torrent_handle that represents the same
        # torrent. Make sure that when we add it to a dict, it just replaces the
        # existing object
        t = self.ses.get_torrents()
        self.assertEqual(len(t), 1)
        for h in t:
            torrents[h] = 'bar'

        self.assertEqual(len(torrents), 1)
        self.assertEqual(torrents[self.h], 'bar')

    def test_replace_trackers(self):
        self.setup()
        trackers = []
        for idx, tracker_url in enumerate(('udp://tracker1.com', 'udp://tracker2.com')):
            tracker = lt.announce_entry(tracker_url)
            tracker.tier = idx
            tracker.fail_limit = 2
            trackers.append(tracker)
            self.assertEqual(tracker.url, tracker_url)
        self.h.replace_trackers(trackers)
        new_trackers = self.h.trackers()
        self.assertEqual(new_trackers[0]['url'], 'udp://tracker1.com')
        self.assertEqual(new_trackers[1]['tier'], 1)
        self.assertEqual(new_trackers[1]['fail_limit'], 2)

    def test_pickle_trackers(self):
        """Test lt objects convertors are working and trackers can be pickled"""
        self.setup()
        tracker = lt.announce_entry('udp://tracker1.com')
        tracker.tier = 0
        tracker.fail_limit = 1
        trackers = [tracker]
        self.h.replace_trackers(trackers)
        # wait a bit until the endpoints list gets populated
        while len(self.h.trackers()[0]['endpoints']) == 0:
            time.sleep(0.1)

        trackers = self.h.trackers()
        self.assertEqual(trackers[0]['url'], 'udp://tracker1.com')
        # this is not necessarily 0, it could also be (EHOSTUNREACH) if the
        # local machine doesn't support the address family
        expect_value = trackers[0]['endpoints'][0]['info_hashes'][0]['last_error']['value']
        pickled_trackers = pickle.dumps(trackers)
        unpickled_trackers = pickle.loads(pickled_trackers)
        self.assertEqual(unpickled_trackers[0]['url'], 'udp://tracker1.com')
        self.assertEqual(unpickled_trackers[0]['endpoints'][0]['info_hashes'][0]['last_error']['value'], expect_value)

    def test_file_status(self):
        self.setup()
        status = self.h.file_status()
        print(status)

    def test_piece_deadlines(self):
        self.setup()
        self.h.clear_piece_deadlines()

    def test_status_last_uploaded_dowloaded(self):
        # we want to check at seconds precision but can't control session
        # time, wait for next full second to prevent second increment
        time.sleep(1 - datetime.datetime.now().microsecond / 1000000.0)

        self.setup()
        st = self.h.status()
        for attr in dir(st):
            print('%s: %s' % (attr, getattr(st, attr)))
        # last upload and download times are at session start time
        self.assertEqual(st.last_upload, None)
        self.assertEqual(st.last_download, None)

    def test_serialize_trackers(self):
        """Test to ensure the dict contains only python built-in types"""
        self.setup()
        self.h.add_tracker({'url': 'udp://tracker1.com'})
        tr = self.h.trackers()[0]
        # wait a bit until the endpoints list gets populated
        while len(tr['endpoints']) == 0:
            time.sleep(0.1)
            tr = self.h.trackers()[0]
        import json
        print(json.dumps(self.h.trackers()[0]))

    def test_torrent_status(self):
        self.setup()
        st = self.h.status()
        ti = st.handle
        self.assertEqual(ti.info_hashes(), self.ti.info_hashes())
        # make sure we can compare torrent_status objects
        st2 = self.h.status()
        self.assertEqual(st2, st)
        print(st2)

    def test_read_resume_data(self):

        resume_data = lt.bencode({
            'file-format': 'libtorrent resume file',
            'info-hash': 'abababababababababab',
            'name': 'test',
            'save_path': '.',
            'peers': '\x01\x01\x01\x01\x00\x01\x02\x02\x02\x02\x00\x02',
            'file_priority': [0, 1, 1]})
        tp = lt.read_resume_data(resume_data)

        self.assertEqual(tp.name, 'test')
        self.assertEqual(tp.info_hashes.v1, lt.sha1_hash('abababababababababab'))
        self.assertEqual(tp.file_priorities, [0, 1, 1])
        self.assertEqual(tp.peers, [('1.1.1.1', 1), ('2.2.2.2', 2)])

        ses = lt.session(settings)
        h = ses.add_torrent(tp)
        for attr in dir(tp):
            print('%s: %s' % (attr, getattr(tp, attr)))

        h.connect_peer(('3.3.3.3', 3))

        for i in range(0, 10):
            alerts = ses.pop_alerts()
            for a in alerts:
                print(a.message())
            time.sleep(0.1)

    def test_scrape(self):
        self.setup()
        # this is just to make sure this function can be called like this
        # from python
        self.h.scrape_tracker()

    def test_unknown_torrent_parameter(self):
        self.ses = lt.session(settings)
        try:
            self.h = self.ses.add_torrent({'unexpected-key-name': ''})
            self.assertFalse('should have thrown an exception')
        except KeyError as e:
            print(e)

    def test_torrent_parameter(self):
        self.ses = lt.session(settings)
        self.ti = lt.torrent_info('url_seed_multi.torrent')
        self.h = self.ses.add_torrent({
            'ti': self.ti,
            'save_path': os.getcwd(),
            'trackers': ['http://test.com/announce'],
            'dht_nodes': [('1.2.3.4', 6881), ('4.3.2.1', 6881)],
            'file_priorities': [1, 1],
            'http_seeds': ['http://test.com/file3'],
            'url_seeds': ['http://test.com/announce-url'],
            'peers': [('5.6.7.8', 6881)],
            'banned_peers': [('8.7.6.5', 6881)],
            'renamed_files': {0: 'test.txt', 2: 'test.txt'}
        })
        self.st = self.h.status()
        self.assertEqual(self.st.save_path, os.getcwd())
        trackers = self.h.trackers()
        self.assertEqual(len(trackers), 1)
        self.assertEqual(trackers[0].get('url'), 'http://test.com/announce')
        self.assertEqual(trackers[0].get('tier'), 0)
        self.assertEqual(self.h.get_file_priorities(), [1, 1])
        self.assertEqual(self.h.http_seeds(), ['http://test.com/file3'])
        # url_seeds was already set, test that it did not get overwritten
        self.assertEqual(self.h.url_seeds(),
                         ['http://test.com/announce-url/', 'http://test.com/file/'])
        # piece priorities weren't set explicitly, but they were updated by the
        # file priorities being set
        self.assertEqual(self.h.get_piece_priorities(), [1])
        self.assertEqual(self.st.verified_pieces, [])


class TestAddPiece(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.session = lt.session(settings)
        self.ti = lt.torrent_info(dummy_data.DICT)
        self.atp = lt.add_torrent_params()
        self.atp.ti = self.ti
        self.atp.save_path = self.dir.name
        self.handle = self.session.add_torrent(self.atp)
        self.wait_for(lambda: self.handle.status().state != lt.torrent_status.checking_files
                      and self.handle.status().state != lt.torrent_status.checking_resume_data, msg="checking")

    def wait_for(self, condition, msg="condition", timeout=5):
        deadline = time.time() + timeout
        while not condition():
            self.assertLess(time.time(), deadline, msg="%s timed out" % msg)
            time.sleep(0.1)

    def wait_until_torrent_finished(self):
        self.wait_for(lambda: self.handle.status().progress == 1.0, msg="progress")

        def file_written():
            with open(os.path.join(self.dir.name.encode(), dummy_data.NAME), mode="rb") as f:
                return f.read() == dummy_data.DATA

        self.wait_for(file_written, msg="file write")

    def test_with_str(self):
        for i, data in enumerate(dummy_data.PIECES):
            self.handle.add_piece(i, data.decode(), 0)

        self.wait_until_torrent_finished()

    def test_with_bytes(self):
        for i, data in enumerate(dummy_data.PIECES):
            self.handle.add_piece(i, data, 0)

        self.wait_until_torrent_finished()


class test_torrent_info(unittest.TestCase):

    def test_non_ascii_file(self):
        try:
            shutil.copy('base.torrent', 'base-\u745E\u5177.torrent')
        except shutil.SameFileError:
            pass
        ti = lt.torrent_info('base-\u745E\u5177.torrent')

        self.assertTrue(len(ti.info_section()) != 0)
        self.assertTrue(len(ti.hash_for_piece(0)) != 0)

    def test_bencoded_constructor(self):
        # things that can be converted to a bencoded entry, will be interpreted
        # as such and encoded
        info = lt.torrent_info({'info': {
            'name': 'test_torrent', 'length': 1234,
            'piece length': 16 * 1024,
            'pieces': 'aaaaaaaaaaaaaaaaaaaa'}})

        self.assertEqual(info.num_files(), 1)

        f = info.files()
        self.assertEqual(f.file_path(0), 'test_torrent')
        self.assertEqual(f.file_name(0), 'test_torrent')
        self.assertEqual(f.file_size(0), 1234)
        self.assertEqual(info.total_size(), 1234)
        self.assertEqual(info.creation_date(), 0)

    def test_bytearray(self):
        # a bytearray object is interpreted as a bencoded buffer
        info = lt.torrent_info(bytearray(lt.bencode({'info': {
            'name': 'test_torrent', 'length': 1234,
            'piece length': 16 * 1024,
            'pieces': 'aaaaaaaaaaaaaaaaaaaa'}})))
        self.assertEqual(info.num_files(), 1)

    def test_bytes(self):
        # a bytes object is interpreted as a bencoded buffer
        info = lt.torrent_info(bytes(lt.bencode({'info': {
            'name': 'test_torrent', 'length': 1234,
            'piece length': 16 * 1024,
            'pieces': 'aaaaaaaaaaaaaaaaaaaa'}})))
        self.assertEqual(info.num_files(), 1)

    def test_load_decode_depth_limit(self):
        self.assertRaises(RuntimeError, lambda: lt.torrent_info(
            {'test': {'test': {'test': {'test': {'test': {}}}}}, 'info': {
                'name': 'test_torrent', 'length': 1234,
                'piece length': 16 * 1024,
                'pieces': 'aaaaaaaaaaaaaaaaaaaa'}}, {'max_decode_depth': 1}))

    def test_load_max_pieces_limit(self):
        self.assertRaises(RuntimeError, lambda: lt.torrent_info(
            {'info': {
                'name': 'test_torrent', 'length': 1234000,
                'piece length': 16 * 1024,
                'pieces': 'aaaaaaaaaaaaaaaaaaaa'}}, {'max_pieces': 1}))

    def test_load_max_buffer_size_limit(self):
        self.assertRaises(RuntimeError, lambda: lt.torrent_info(
            {'info': {
                'name': 'test_torrent', 'length': 1234000,
                'piece length': 16 * 1024,
                'pieces': 'aaaaaaaaaaaaaaaaaaaa'}}, {'max_buffer_size': 1}))

    def test_info_section(self):
        ti = lt.torrent_info('base.torrent')

        self.assertTrue(len(ti.info_section()) != 0)
        self.assertTrue(len(ti.hash_for_piece(0)) != 0)

    def test_torrent_info_bytes_overload(self):
        # bytes will never be interpreted as a file name. It's interpreted as a
        # bencoded buffer
        with self.assertRaises(RuntimeError):
            ti = lt.torrent_info(b'base.torrent')

    def test_web_seeds(self):
        ti = lt.torrent_info('base.torrent')

        ws = [{'url': 'http://foo/test', 'auth': '', 'type': 0},
              {'url': 'http://bar/test', 'auth': '', 'type': 1}]
        ti.set_web_seeds(ws)
        web_seeds = ti.web_seeds()
        self.assertEqual(len(ws), len(web_seeds))
        for i in range(len(web_seeds)):
            self.assertEqual(web_seeds[i]["url"], ws[i]["url"])
            self.assertEqual(web_seeds[i]["auth"], ws[i]["auth"])
            self.assertEqual(web_seeds[i]["type"], ws[i]["type"])

    def test_announce_entry(self):
        ae = lt.announce_entry('test')
        self.assertEqual(ae.url, 'test')
        self.assertEqual(ae.tier, 0)
        self.assertEqual(ae.verified, False)
        self.assertEqual(ae.source, 0)

    def test_torrent_info_sha1_overload(self):
        ti = lt.torrent_info(lt.info_hash_t(lt.sha1_hash(b'a' * 20)))
        self.assertEqual(ti.info_hash(), lt.sha1_hash(b'a' * 20))
        self.assertEqual(ti.info_hashes().v1, lt.sha1_hash(b'a' * 20))

        ti_copy = lt.torrent_info(ti)
        self.assertEqual(ti_copy.info_hash(), lt.sha1_hash(b'a' * 20))
        self.assertEqual(ti_copy.info_hashes().v1, lt.sha1_hash(b'a' * 20))

    def test_torrent_info_sha256_overload(self):
        ti = lt.torrent_info(lt.info_hash_t(lt.sha256_hash(b'a' * 32)))
        self.assertEqual(ti.info_hashes().v2, lt.sha256_hash(b'a' * 32))

        ti_copy = lt.torrent_info(ti)
        self.assertEqual(ti_copy.info_hashes().v2, lt.sha256_hash(b'a' * 32))

    def test_url_seed(self):
        ti = lt.torrent_info('base.torrent')

        ti.add_tracker('foobar1')
        ti.add_url_seed('foobar2')
        ti.add_url_seed('foobar3', 'username:password')
        ti.add_url_seed('foobar4', 'username:password', [])

        seeds = ti.web_seeds()
        self.assertEqual(seeds, [
            {'url': 'foobar2', 'type': 0, 'auth': ''},
            {'url': 'foobar3', 'type': 0, 'auth': 'username:password'},
            {'url': 'foobar4', 'type': 0, 'auth': 'username:password'},
        ])

    def test_http_seed(self):
        ti = lt.torrent_info('base.torrent')

        ti.add_http_seed('foobar2')
        ti.add_http_seed('foobar3', 'username:password')
        ti.add_http_seed('foobar4', 'username:password', [])

        seeds = ti.web_seeds()
        self.assertEqual(seeds, [
            {'url': 'foobar2', 'type': 1, 'auth': ''},
            {'url': 'foobar3', 'type': 1, 'auth': 'username:password'},
            {'url': 'foobar4', 'type': 1, 'auth': 'username:password'},
        ])

class test_alerts(unittest.TestCase):

    def test_alert(self):

        ses = lt.session(settings)
        ti = lt.torrent_info('base.torrent')
        h = ses.add_torrent({'ti': ti, 'save_path': os.getcwd()})
        st = h.status()
        time.sleep(1)
        ses.remove_torrent(h)
        ses.wait_for_alert(1000)  # milliseconds
        alerts = ses.pop_alerts()
        for a in alerts:
            if a.what() == 'add_torrent_alert':
                self.assertEqual(a.torrent_name, 'temp')
            print(a.message())
            for field_name in dir(a):
                if field_name.startswith('__'):
                    continue
                field = getattr(a, field_name)
                if callable(field):
                    print('  ', field_name, ' = ', field())
                else:
                    print('  ', field_name, ' = ', field)

        print(st.next_announce)
        self.assertEqual(st.name, 'temp')
        print(st.errc.message())
        print(st.pieces)
        print(st.last_seen_complete)
        print(st.completed_time)
        print(st.progress)
        print(st.num_pieces)
        print(st.distributed_copies)
        print(st.info_hashes)
        print(st.seeding_duration)
        print(st.last_upload)
        print(st.last_download)
        self.assertEqual(st.save_path, os.getcwd())

    def test_alert_fs(self):
        ses = lt.session(settings)
        s1, s2 = socket.socketpair()
        ses.set_alert_fd(s2.fileno())

        ses.pop_alerts()

        # make sure there's an alert to wake us up
        ses.post_session_stats()

        read_sockets, write_sockets, error_sockets = select.select([s1], [], [])

        self.assertEqual(len(read_sockets), 1)
        for s in read_sockets:
            s.recv(10)

    def test_pop_alerts(self):
        ses = lt.session(settings)
        ses.async_add_torrent(
            {"ti": lt.torrent_info("base.torrent"), "save_path": "."})

# this will cause an error (because of duplicate torrents) and the
# torrent_info object created here will be deleted once the alert goes out
# of scope. When that happens, it will decrement the python object, to allow
# it to release the object.
# we're trying to catch the error described in this post, with regards to
# torrent_info.
# https://mail.python.org/pipermail/cplusplus-sig/2007-June/012130.html
        ses.async_add_torrent(
            {"ti": lt.torrent_info("base.torrent"), "save_path": "."})
        time.sleep(1)
        for i in range(0, 10):
            alerts = ses.pop_alerts()
            for a in alerts:
                print(a.message())
            time.sleep(0.1)

    def test_alert_notify(self):
        ses = lt.session(settings)
        event = threading.Event()

        def callback():
            event.set()

        ses.set_alert_notify(callback)
        ses.async_add_torrent(
            {"ti": lt.torrent_info("base.torrent"), "save_path": "."})
        event.wait()


class test_bencoder(unittest.TestCase):

    def test_bencode(self):
        encoded = lt.bencode({'a': 1, 'b': [1, 2, 3], 'c': 'foo'})
        self.assertEqual(encoded, b'd1:ai1e1:bli1ei2ei3ee1:c3:fooe')

    def test_bdecode(self):
        encoded = b'd1:ai1e1:bli1ei2ei3ee1:c3:fooe'
        decoded = lt.bdecode(encoded)
        self.assertEqual(decoded, {b'a': 1, b'b': [1, 2, 3], b'c': b'foo'})

    def test_string(self):
        encoded = lt.bencode('foo\u00e5\u00e4\u00f6')
        self.assertEqual(encoded, b'9:foo\xc3\xa5\xc3\xa4\xc3\xb6')

    def test_bytes(self):
        encoded = lt.bencode(b'foo')
        self.assertEqual(encoded, b'3:foo')

    def test_float(self):
        # TODO: this should throw a TypeError in the future
        with self.assertWarns(DeprecationWarning):
            encoded = lt.bencode(1.337)
            self.assertEqual(encoded, b'0:')

    def test_object(self):
        class FooBar:
            dummy = 1

        # TODO: this should throw a TypeError in the future
        with self.assertWarns(DeprecationWarning):
            encoded = lt.bencode(FooBar())
            self.assertEqual(encoded, b'0:')

    def test_preformatted(self):
        encoded = lt.bencode((1, 2, 3, 4, 5))
        self.assertEqual(encoded, b'\x01\x02\x03\x04\x05')

class test_sha1hash(unittest.TestCase):

    def test_sha1hash(self):
        h = 'a0' * 20
        s = lt.sha1_hash(binascii.unhexlify(h))
        self.assertEqual(h, str(s))

    def test_hash(self):
        self.assertNotEqual(hash(lt.sha1_hash(b'b' * 20)), hash(lt.sha1_hash(b'a' * 20)))
        self.assertEqual(hash(lt.sha1_hash(b'b' * 20)), hash(lt.sha1_hash(b'b' * 20)))

class test_sha256hash(unittest.TestCase):

    def test_sha1hash(self):
        h = 'a0' * 32
        s = lt.sha256_hash(binascii.unhexlify(h))
        self.assertEqual(h, str(s))

    def test_hash(self):
        self.assertNotEqual(hash(lt.sha256_hash(b'b' * 32)), hash(lt.sha256_hash(b'a' * 32)))
        self.assertEqual(hash(lt.sha256_hash(b'b' * 32)), hash(lt.sha256_hash(b'b' * 32)))

class test_info_hash(unittest.TestCase):

    def test_info_hash(self):
        s1 = lt.sha1_hash(b'a' * 20)
        s2 = lt.sha256_hash(b'b' * 32)

        ih1 = lt.info_hash_t(s1);
        self.assertTrue(ih1.has_v1())
        self.assertFalse(ih1.has_v2())
        self.assertEqual(ih1.v1, s1)

        ih2 = lt.info_hash_t(s2);
        self.assertFalse(ih2.has_v1())
        self.assertTrue(ih2.has_v2())
        self.assertEqual(ih2.v2, s2)

        ih12 = lt.info_hash_t(s1, s2);
        self.assertTrue(ih12.has_v1())
        self.assertTrue(ih12.has_v2())
        self.assertEqual(ih12.v1, s1)
        self.assertEqual(ih12.v2, s2)

        self.assertNotEqual(hash(ih1), hash(ih2))
        self.assertNotEqual(hash(ih1), hash(ih12))
        self.assertEqual(hash(ih1), hash(lt.info_hash_t(s1)))
        self.assertEqual(hash(ih2), hash(lt.info_hash_t(s2)))
        self.assertEqual(hash(ih12), hash(lt.info_hash_t(s1, s2)))

class test_magnet_link(unittest.TestCase):

    def test_parse_magnet_uri(self):
        ses = lt.session({})
        magnet = 'magnet:?xt=urn:btih:C6EIF4CCYDBTIJVG3APAGM7M4NDONCTI'
        p = lt.parse_magnet_uri(magnet)
        self.assertEqual(str(p.info_hashes.v1), '178882f042c0c33426a6d81e0333ece346e68a68')
        p.save_path = '.'
        h = ses.add_torrent(p)
        self.assertEqual(str(h.info_hash()), '178882f042c0c33426a6d81e0333ece346e68a68')
        self.assertEqual(str(h.info_hashes().v1), '178882f042c0c33426a6d81e0333ece346e68a68')

    def test_parse_magnet_uri_dict(self):
        ses = lt.session({})
        magnet = 'magnet:?xt=urn:btih:C6EIF4CCYDBTIJVG3APAGM7M4NDONCTI'
        p = lt.parse_magnet_uri_dict(magnet)
        self.assertEqual(binascii.hexlify(p['info_hashes']), b'178882f042c0c33426a6d81e0333ece346e68a68')
        p['save_path'] = '.'
        h = ses.add_torrent(p)
        self.assertEqual(str(h.info_hash()), '178882f042c0c33426a6d81e0333ece346e68a68')
        self.assertEqual(str(h.info_hashes().v1), '178882f042c0c33426a6d81e0333ece346e68a68')

    def test_add_deprecated_magnet_link(self):
        ses = lt.session()
        atp = lt.add_torrent_params()
        atp.info_hashes = lt.info_hash_t(lt.sha1_hash(b"a" * 20))
        h = ses.add_torrent(atp)

        self.assertTrue(h.status().info_hashes == lt.info_hash_t(lt.sha1_hash(b"a" * 20)))

    def test_add_magnet_link(self):
        ses = lt.session()
        atp = lt.add_torrent_params()
        atp.info_hash = lt.sha1_hash(b"a" * 20)
        h = ses.add_torrent(atp)

        self.assertTrue(h.status().info_hashes == lt.info_hash_t(lt.sha1_hash(b"a" * 20)))


class test_peer_class(unittest.TestCase):

    def test_peer_class_ids(self):
        s = lt.session(settings)

        print('global_peer_class_id:', lt.session.global_peer_class_id)
        print('tcp_peer_class_id:', lt.session.tcp_peer_class_id)
        print('local_peer_class_id:', lt.session.local_peer_class_id)

        print('global: ', s.get_peer_class(s.global_peer_class_id))
        print('tcp: ', s.get_peer_class(s.local_peer_class_id))
        print('local: ', s.get_peer_class(s.local_peer_class_id))

    def test_peer_class(self):
        s = lt.session(settings)

        c = s.create_peer_class('test class')
        print('new class: ', s.get_peer_class(c))

        nfo = s.get_peer_class(c)
        self.assertEqual(nfo['download_limit'], 0)
        self.assertEqual(nfo['upload_limit'], 0)
        self.assertEqual(nfo['ignore_unchoke_slots'], False)
        self.assertEqual(nfo['connection_limit_factor'], 100)
        self.assertEqual(nfo['download_priority'], 1)
        self.assertEqual(nfo['upload_priority'], 1)
        self.assertEqual(nfo['label'], 'test class')

        nfo['download_limit'] = 1337
        nfo['upload_limit'] = 1338
        nfo['ignore_unchoke_slots'] = True
        nfo['connection_limit_factor'] = 42
        nfo['download_priority'] = 2
        nfo['upload_priority'] = 3

        s.set_peer_class(c, nfo)

        nfo2 = s.get_peer_class(c)
        self.assertEqual(nfo, nfo2)

    def test_peer_class_filter(self):
        filt = lt.peer_class_type_filter()
        filt.add(lt.peer_class_type_filter.tcp_socket, lt.session.global_peer_class_id)
        filt.remove(lt.peer_class_type_filter.utp_socket, lt.session.local_peer_class_id)

        filt.disallow(lt.peer_class_type_filter.tcp_socket, lt.session.global_peer_class_id)
        filt.allow(lt.peer_class_type_filter.utp_socket, lt.session.local_peer_class_id)

    def test_peer_class_ip_filter(self):
        s = lt.session(settings)
        s.set_peer_class_type_filter(lt.peer_class_type_filter())
        s.set_peer_class_filter(lt.ip_filter())

class test_ip_filter(unittest.TestCase):

    def test_export(self):

        f = lt.ip_filter()
        self.assertEqual(f.access('1.1.1.1'), 0)
        f.add_rule('1.1.1.1', '1.1.1.2', 1)
        self.assertEqual(f.access('1.1.1.0'), 0)
        self.assertEqual(f.access('1.1.1.1'), 1)
        self.assertEqual(f.access('1.1.1.2'), 1)
        self.assertEqual(f.access('1.1.1.3'), 0)
        exp = f.export_filter()
        self.assertEqual(exp, ([('0.0.0.0', '1.1.1.0'), ('1.1.1.1', '1.1.1.2'), ('1.1.1.3', '255.255.255.255')], [('::', 'ffff:ffff:ffff:ffff:ffff:ffff:ffff:ffff')]))

class test_session(unittest.TestCase):

    def test_settings(self):
        sett = { 'alert_mask': lt.alert.category_t.all_categories }
        s = lt.session(sett)
        sett = s.get_settings()
        self.assertEqual(sett['alert_mask'] & 0x7fffffff, 0x7fffffff)

    def test_session_params(self):
        sp = lt.session_params()
        sp.settings = { 'alert_mask': lt.alert.category_t.all_categories }
        s = lt.session(sp)
        sett = s.get_settings()
        self.assertEqual(sett['alert_mask'] & 0x7fffffff, 0x7fffffff)

    def test_session_params_roundtrip_buf(self):

        sp = lt.session_params()
        sp.settings = { 'alert_mask': lt.alert.category_t.all_categories }

        buf = lt.write_session_params_buf(sp)
        sp2 = lt.read_session_params(buf)
        self.assertEqual(sp2.settings['alert_mask'] & 0x7fffffff, 0x7fffffff)

    def test_session_params_roundtrip_entry(self):

        sp = lt.session_params()
        sp.settings = { 'alert_mask': lt.alert.category_t.all_categories }

        ent = lt.write_session_params(sp)
        print(ent)
        sp2 = lt.read_session_params(ent)
        self.assertEqual(sp2.settings['alert_mask'] & 0x7fffffff, 0x7fffffff)

    def test_add_torrent(self):
        s = lt.session(settings)
        h = s.add_torrent({'ti': lt.torrent_info('base.torrent'),
                       'save_path': '.',
                       'dht_nodes': [('1.2.3.4', 6881), ('4.3.2.1', 6881)],
                       'http_seeds': ['http://test.com/seed'],
                       'peers': [('5.6.7.8', 6881)],
                       'banned_peers': [('8.7.6.5', 6881)],
                       'file_priorities': [1, 1, 1, 2, 0]})

    def test_find_torrent(self):
        s = lt.session(settings)
        h = s.add_torrent({'info_hash': b"a" * 20,
                           'save_path': '.'})
        self.assertTrue(h.is_valid())

        h2 = s.find_torrent(lt.sha1_hash(b"a" * 20))
        self.assertTrue(h2.is_valid())
        h3 = s.find_torrent(lt.sha1_hash(b"b" * 20))
        self.assertFalse(h3.is_valid())

        self.assertEqual(h, h2)
        self.assertNotEqual(h, h3)

    def test_add_torrent_info_hash(self):
        s = lt.session(settings)
        h = s.add_torrent({
                           'info_hash': b'a' * 20,
                           'info_hashes': b'a' * 32,
                           'save_path': '.'})

        time.sleep(1)
        alerts = s.pop_alerts()

        while len(alerts) > 0:
            a = alerts.pop(0)
            print(a)

        self.assertTrue(h.is_valid())
        self.assertEqual(h.status().info_hashes, lt.info_hash_t(lt.sha1_hash(b'a' * 20), lt.sha256_hash(b'a' * 32)))

    def test_session_status(self):
        if not has_deprecated():
            return

        s = lt.session()
        st = s.status()
        print(st)
        print(st.active_requests)
        print(st.dht_nodes)
        print(st.dht_node_cache)
        print(st.dht_torrents)
        print(st.dht_global_nodes)
        print(st.dht_total_allocations)

    def test_apply_settings(self):

        s = lt.session(settings)
        s.apply_settings({'num_want': 66, 'user_agent': 'test123'})
        self.assertEqual(s.get_settings()['num_want'], 66)
        self.assertEqual(s.get_settings()['user_agent'], 'test123')

    def test_post_session_stats(self):
        s = lt.session({'alert_mask': 0, 'enable_dht': False})
        s.post_session_stats()
        alerts = []
        # first the stats headers log line. but not if logging is disabled
        while len(alerts) == 0:
            s.wait_for_alert(1000)
            alerts = s.pop_alerts()

        while len(alerts) > 0:
            a = alerts.pop(0)
            print(a)
            if isinstance(a, lt.session_stats_header_alert):
                break
        self.assertTrue(isinstance(a, lt.session_stats_header_alert))
        # then the actual stats values
        while len(alerts) == 0:
            s.wait_for_alert(1000)
            alerts = s.pop_alerts()
        a = alerts.pop(0)
        print(a)
        self.assertTrue(isinstance(a, lt.session_stats_alert))
        self.assertTrue(isinstance(a.values, dict))
        self.assertTrue(len(a.values) > 0)

    def test_post_dht_stats(self):
        s = lt.session({'alert_mask': 0, 'enable_dht': False})
        s.post_dht_stats()
        alerts = []
        cnt = 0
        while len(alerts) == 0:
            s.wait_for_alert(1000)
            alerts = s.pop_alerts()
            cnt += 1
            if cnt > 60:
                print('no dht_stats_alert in 1 minute!')
                sys.exit(1)
        a = alerts.pop(0)
        self.assertTrue(isinstance(a, lt.dht_stats_alert))
        self.assertTrue(isinstance(a.active_requests, list))
        self.assertTrue(isinstance(a.routing_table, list))

    def test_unknown_settings(self):
        try:
            lt.session({'unexpected-key-name': 42})
            self.assertFalse('should have thrown an exception')
        except KeyError as e:
            print(e)

    def test_fingerprint(self):
        self.assertEqual(lt.generate_fingerprint('LT', 0, 1, 2, 3), '-LT0123-')
        self.assertEqual(lt.generate_fingerprint('..', 10, 1, 2, 3), '-..A123-')

    def test_min_memory_preset(self):
        min_mem = lt.min_memory_usage()
        print(min_mem)

        self.assertTrue('connection_speed' in min_mem)
        self.assertTrue('file_pool_size' in min_mem)

    def test_seed_mode_preset(self):
        seed_mode = lt.high_performance_seed()
        print(seed_mode)

        self.assertTrue('alert_queue_size' in seed_mode)
        self.assertTrue('connection_speed' in seed_mode)
        self.assertTrue('file_pool_size' in seed_mode)

    def test_default_settings(self):

        default = lt.default_settings()
        print(default)


class test_example_client(unittest.TestCase):

    def test_execute_client(self):
        if os.name == 'nt':
            # TODO: fix windows includes of client.py
            return
        my_stdin = sys.stdin
        if os.name != 'nt':
            master_fd, slave_fd = pty.openpty()
            # slave_fd fix multiple stdin assignment at termios.tcgetattr
            my_stdin = slave_fd

        process = sub.Popen(
            [sys.executable, "client.py", "url_seed_multi.torrent"],
            stdin=my_stdin, stdout=sub.PIPE, stderr=sub.PIPE)
        # python2 has no Popen.wait() timeout
        time.sleep(5)
        returncode = process.poll()
        if returncode is None:
            # this is an expected use-case
            process.kill()
        err = process.stderr.read().decode("utf-8")
        self.assertEqual('', err, 'process throw errors: \n' + err)
        # check error code if process did unexpected end
        if returncode is not None:
            # in case of error return: output stdout if nothing was on stderr
            if returncode != 0:
                print("stdout:\n" + process.stdout.read().decode("utf-8"))
            self.assertEqual(returncode, 0, "returncode: " + str(returncode) + "\n"
                             + "stderr: empty\n"
                             + "some configuration does not output errors like missing module members,"
                             + "try to call it manually to get the error message\n")

    def test_execute_simple_client(self):
        process = sub.Popen(
            [sys.executable, "simple_client.py", "url_seed_multi.torrent"],
            stdout=sub.PIPE, stderr=sub.PIPE)
        # python2 has no Popen.wait() timeout
        time.sleep(5)
        returncode = process.poll()
        if returncode is None:
            # this is an expected use-case
            process.kill()
        err = process.stderr.read().decode("utf-8")
        self.assertEqual('', err, 'process throw errors: \n' + err)
        # check error code if process did unexpected end
        if returncode is not None:
            # in case of error return: output stdout if nothing was on stderr
            if returncode != 0:
                print("stdout:\n" + process.stdout.read().decode("utf-8"))
            self.assertEqual(returncode, 0, "returncode: " + str(returncode) + "\n"
                             + "stderr: empty\n"
                             + "some configuration does not output errors like missing module members,"
                             + "try to call it manually to get the error message\n")

    def test_execute_make_torrent(self):
        process = sub.Popen(
            [sys.executable, "make_torrent.py", "url_seed_multi.torrent",
             "http://test.com/test"], stdout=sub.PIPE, stderr=sub.PIPE)
        returncode = process.wait()
        # python2 has no Popen.wait() timeout
        err = process.stderr.read().decode("utf-8")
        self.assertEqual('', err, 'process throw errors: \n' + err)
        # in case of error return: output stdout if nothing was on stderr
        if returncode != 0:
            print("stdout:\n" + process.stdout.read().decode("utf-8"))
        self.assertEqual(returncode, 0, "returncode: " + str(returncode) + "\n"
                         + "stderr: empty\n"
                         + "some configuration does not output errors like missing module members,"
                         + "try to call it manually to get the error message\n")

    def test_default_settings(self):

        default = lt.default_settings()
        self.assertNotIn('', default)
        print(default)


class test_operation_t(unittest.TestCase):

    def test_enum(self):
        self.assertEqual(lt.operation_name(lt.operation_t.sock_accept), "sock_accept")
        self.assertEqual(lt.operation_name(lt.operation_t.unknown), "unknown")
        self.assertEqual(lt.operation_name(lt.operation_t.mkdir), "mkdir")
        self.assertEqual(lt.operation_name(lt.operation_t.partfile_write), "partfile_write")
        self.assertEqual(lt.operation_name(lt.operation_t.hostname_lookup), "hostname_lookup")


class test_error_code(unittest.TestCase):

    def test_error_code(self):

        a = lt.error_code()
        a = lt.error_code(10, lt.libtorrent_category())
        self.assertEqual(a.category().name(), 'libtorrent')

        self.assertEqual(lt.libtorrent_category().name(), 'libtorrent')
        self.assertEqual(lt.upnp_category().name(), 'upnp')
        self.assertEqual(lt.http_category().name(), 'http')
        self.assertEqual(lt.socks_category().name(), 'socks')
        self.assertEqual(lt.bdecode_category().name(), 'bdecode')
        self.assertEqual(lt.generic_category().name(), 'generic')
        self.assertEqual(lt.system_category().name(), 'system')


class test_peer_info(unittest.TestCase):

    def test_peer_info_members(self):

        p = lt.peer_info()

        print(p.client)
        print(p.pieces)
        print(p.pieces)
        print(p.last_request)
        print(p.last_active)
        print(p.flags)
        print(p.source)
        print(p.pid)
        print(p.downloading_piece_index)
        print(p.ip)
        print(p.local_endpoint)
        print(p.read_state)
        print(p.write_state)


if __name__ == '__main__':
    print(lt.__version__)
    try:
        shutil.copy(os.path.join('..', '..', 'test', 'test_torrents',
                                 'url_seed_multi.torrent'), '.')
    except shutil.SameFileError:
        pass
    try:
        shutil.copy(os.path.join('..', '..', 'test', 'test_torrents',
                                 'base.torrent'), '.')
    except shutil.SameFileError:
        pass
    try:
        shutil.copy(os.path.join('..', '..', 'test', 'test_torrents',
                                 'unordered.torrent'), '.')
    except shutil.SameFileError:
        pass
    unittest.main()

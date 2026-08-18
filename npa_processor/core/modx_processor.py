"""Модуль обработки НПА через MODX CMS.

Содержит класс MODXHTMLProcessor для пакетной обработки документов,
загрузки через SSH/SFTP и обновления MySQL базы данных MODX.
"""

import sys
import os
import threading
import logging
from logging.handlers import RotatingFileHandler
from datetime import timedelta, datetime
import paramiko
import pymysql
from pymysql.cursors import DictCursor
import socket
from functools import lru_cache
import re
import json
import tempfile
import shlex
import uuid as _uuid

from npa_processor.config import get_modx_db_config, get_settings
from npa_processor.core.html_parser import QueueHandler

settings = get_settings()

class MODXHTMLProcessor:
    def __init__(self, log_queue=None):
        self.ssh_host = settings.modx_ssh_host
        self.ssh_port = settings.modx_ssh_port
        self.ssh_username = settings.modx_ssh_username
        self.ssh_password = settings.modx_ssh_password
        self.db_config = get_modx_db_config()
        self.base_path = settings.modx_base_path
        self.ssh = None
        self.sftp = None
        self._connection_pool = []
        self._pool_lock = threading.Lock()
        self._max_connections = 10
        self._resource_cache = {}
        self._cache_expiry = {}
        self._cache_lock = threading.Lock()
        self._cache_ttl = timedelta(minutes=5)
        self._init_db_pool()
        self.log_queue = log_queue
        log_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        log_file = 'modx_processor.log'
        handler = RotatingFileHandler(log_file, maxBytes=10*1024*1024, backupCount=5)
        handler.setFormatter(log_formatter)
        self.logger = logging.getLogger('MODXProcessor')
        self.logger.setLevel(logging.INFO)
        self.logger.addHandler(handler)
        if self.log_queue:
            queue_handler = QueueHandler(self.log_queue)
            queue_handler.setFormatter(log_formatter)
            self.logger.addHandler(queue_handler)

    def _init_db_pool(self):
        try:
            for _ in range(2):
                conn = pymysql.connect(
                    host=self.db_config['host'],
                    port=self.db_config['port'],
                    user=self.db_config['user'],
                    password=self.db_config['password'],
                    database=self.db_config['database'],
                    charset=self.db_config['charset'],
                    cursorclass=DictCursor
                )
                self._connection_pool.append(conn)
        except Exception as e:
            raise

    def get_db_connection(self):
        with self._pool_lock:
            if self._connection_pool:
                return self._connection_pool.pop()
            try:
                conn = pymysql.connect(
                    host=self.db_config['host'],
                    port=self.db_config['port'],
                    user=self.db_config['user'],
                    password=self.db_config['password'],
                    database=self.db_config['database'],
                    charset=self.db_config['charset'],
                    cursorclass=DictCursor
                )
                return conn
            except Exception as e:
                raise Exception(f"Не удалось создать соединение: {e}")

    def release_db_connection(self, conn):
        with self._pool_lock:
            if len(self._connection_pool) < self._max_connections:
                self._connection_pool.append(conn)
            else:
                try:
                    conn.close()
                except Exception:
                    pass

    def close_db_pool(self):
        with self._pool_lock:
            for conn in self._connection_pool:
                try:
                    conn.close()
                except Exception:
                    pass
            self._connection_pool.clear()

    def clear_cache(self):
        with self._cache_lock:
            self._resource_cache.clear()
            self._cache_expiry.clear()

    def get_resource_basic_cached(self, resource_id):
        cache_key = f"resource_basic_{resource_id}"
        current_time = datetime.now()
        with self._cache_lock:
            if (cache_key in self._resource_cache and
                cache_key in self._cache_expiry and
                current_time < self._cache_expiry[cache_key]):
                return self._resource_cache[cache_key]
        connection = self.get_db_connection()
        try:
            with connection.cursor(DictCursor) as cursor:
                sql = """
                SELECT id, pagetitle, longtitle, content, parent, template
                FROM modx_site_content 
                WHERE id = %s AND deleted = 0
                """
                cursor.execute(sql, (resource_id,))
                result = cursor.fetchone()
            with self._cache_lock:
                self._resource_cache[cache_key] = result
                self._cache_expiry[cache_key] = current_time + self._cache_ttl
            return result
        finally:
            if connection:
                self.release_db_connection(connection)

    def get_resource_with_params_cached(self, resource_id):
        cache_key = f"resource_{resource_id}"
        current_time = datetime.now()
        with self._cache_lock:
            if (cache_key in self._resource_cache and
                cache_key in self._cache_expiry and
                current_time < self._cache_expiry[cache_key]):
                return self._resource_cache[cache_key]
        resource_data = self.get_resource_with_params_fast(resource_id)
        with self._cache_lock:
            self._resource_cache[cache_key] = resource_data
            self._cache_expiry[cache_key] = current_time + self._cache_ttl
        return resource_data

    def load_resources_list_optimized(self, law_num_filter=None, resolution_num_filter=None):
        if law_num_filter and law_num_filter.strip():
            resources = self.get_resources_by_law_number(law_num_filter)
            if resources:
                return self._format_resources_list(resources, 'law')
        if resolution_num_filter and resolution_num_filter.strip():
            resources = self.get_resources_by_resolution_number(resolution_num_filter)
            if resources:
                return self._format_resources_list(resources, 'regulation')
        return self.get_all_resources_optimized(law_num_filter, resolution_num_filter)

    def get_all_resources_optimized(self, law_num_filter=None, resolution_num_filter=None):
        connection = self.get_db_connection()
        try:
            with connection.cursor(DictCursor) as cursor:
                sql = """
                SELECT 
                    sc.id, 
                    sc.pagetitle, 
                    sc.parent,
                    sc.template,
                    sc.content,
                    tv6.value as z_vid,
                    tv10.value as z_num,
                    tv12.value as z_data_r
                FROM modx_site_content sc 
                LEFT JOIN modx_site_tmplvar_contentvalues tv6 
                    ON tv6.contentid = sc.id AND tv6.tmplvarid = 6
                LEFT JOIN modx_site_tmplvar_contentvalues tv10 
                    ON tv10.contentid = sc.id AND tv10.tmplvarid = 10
                LEFT JOIN modx_site_tmplvar_contentvalues tv12 
                    ON tv12.contentid = sc.id AND tv12.tmplvarid = 12
                WHERE sc.deleted = 0 
                  AND sc.published = 1
                  AND sc.template IN (12, 103)
                  AND (tv6.value = 'Закон Севастополя' OR tv6.value = 'Постановление ЗС Севастополя')
                """
                params = []
                conditions = []
                if law_num_filter and law_num_filter.strip():
                    law_num = law_num_filter.strip()
                    if not law_num.endswith('-ЗС'):
                        law_num = f"{law_num}-ЗС"
                    conditions.append("(tv6.value = 'Закон Севастополя' AND tv10.value = %s)")
                    params.append(law_num)
                if resolution_num_filter and resolution_num_filter.strip():
                    resolution_num = resolution_num_filter.strip()
                    conditions.append("(tv6.value = 'Постановление ЗС Севастополя' AND tv10.value = %s)")
                    params.append(resolution_num)
                if conditions:
                    sql += " AND (" + " OR ".join(conditions) + ")"
                with connection.cursor(pymysql.cursors.SSCursor) as sscursor:
                    sscursor.execute(sql, params)
                    all_resources_data = []
                    batch_size = 100
                    while True:
                        batch = sscursor.fetchmany(batch_size)
                        if not batch:
                            break
                        all_resources_data.extend(batch)
                columns = [desc[0] for desc in sscursor.description]
                all_resources_data = [dict(zip(columns, row)) for row in all_resources_data]
                parent_ids = [str(res['id']) for res in all_resources_data if res['template'] == 103]
                children_by_parent = {}
                if parent_ids:
                    law_parent_ids = []
                    resolution_parent_ids = []
                    for res in all_resources_data:
                        if res['template'] == 103:
                            if res['z_vid'] == 'Закон Севастополя':
                                law_parent_ids.append(str(res['id']))
                            elif res['z_vid'] == 'Постановление ЗС Севастополя':
                                resolution_parent_ids.append(str(res['id']))
                    children_data = []
                    if law_parent_ids:
                        sql_children_law = f"""
                        SELECT id, pagetitle, content, parent
                        FROM modx_site_content 
                        WHERE deleted = 0 
                          AND published = 1
                          AND parent IN ({','.join(['%s']*len(law_parent_ids))})
                          AND pagetitle LIKE %s
                        """
                        cursor.execute(sql_children_law, law_parent_ids + ['Текст Закона%'])
                        children_data.extend(cursor.fetchall())
                    if resolution_parent_ids:
                        sql_children_resolution = f"""
                        SELECT id, pagetitle, content, parent
                        FROM modx_site_content 
                        WHERE deleted = 0 
                          AND published = 1
                          AND parent IN ({','.join(['%s']*len(resolution_parent_ids))})
                          AND pagetitle LIKE %s
                        """
                        cursor.execute(sql_children_resolution, resolution_parent_ids + ['Текст Постановления%'])
                        children_data.extend(cursor.fetchall())
                    for child in children_data:
                        parent_id = child['parent']
                        if parent_id not in children_by_parent:
                            children_by_parent[parent_id] = []
                        children_by_parent[parent_id].append(child)
                all_resources = []
                processed_ids = set()
                for res in all_resources_data:
                    if res['id'] in processed_ids:
                        continue
                    if res['template'] == 103 and res['id'] in children_by_parent:
                        children = children_by_parent[res['id']]
                        for child in children:
                            if child['id'] not in processed_ids:
                                year = None
                                if res['z_data_r']:
                                    year_match = re.search(r'\b(\d{4})\b', str(res['z_data_r']))
                                    if year_match and 1900 <= int(year_match.group(1)) <= 2100:
                                        year = year_match.group(1)
                                doc_num = res['z_num'] if res['z_num'] else "без номера"
                                doc_type = 'law' if res['z_vid'] and 'Закон' in res['z_vid'] else 'regulation'
                                doc_type_display = 'Закон' if doc_type == 'law' else 'Постановление'
                                all_resources.append({
                                    'id': child['id'],
                                    'display_text': f"{doc_type_display} № {doc_num}",
                                    'pagetitle': child['pagetitle'],
                                    'content': child['content'],
                                    'z_num': doc_num,
                                    'year': year,
                                    'doc_type': doc_type,
                                    'parent_id': res['id'],
                                    'template': 12
                                })
                                processed_ids.add(child['id'])
                    else:
                        year = None
                        if res['z_data_r']:
                            year_match = re.search(r'\b(\d{4})\b', str(res['z_data_r']))
                            if year_match and 1900 <= int(year_match.group(1)) <= 2100:
                                year = year_match.group(1)
                        doc_num = res['z_num'] if res['z_num'] else "без номера"
                        doc_type = 'law' if res['z_vid'] and 'Закон' in res['z_vid'] else 'regulation'
                        doc_type_display = 'Закон' if doc_type == 'law' else 'Постановление'
                        all_resources.append({
                            'id': res['id'],
                            'display_text': f"{doc_type_display} № {doc_num}",
                            'pagetitle': res['pagetitle'],
                            'content': res['content'],
                            'z_num': doc_num,
                            'year': year,
                            'doc_type': doc_type,
                            'parent_id': res['parent'],
                            'template': res['template']
                        })
                        processed_ids.add(res['id'])
                def sort_key(x):
                    doc_type_order = 0 if x['doc_type'] == 'law' else 1
                    num_match = re.search(r'(\d+)', x['z_num'] or '')
                    num = int(num_match.group(1)) if num_match else 0
                    return (doc_type_order, num, x['z_num'] or '')
                all_resources.sort(key=sort_key)
                return all_resources
        except Exception as e:
            raise
        finally:
            if connection:
                self.release_db_connection(connection)

    def get_resources_by_law_number(self, law_number):
        connection = self.get_db_connection()
        try:
            with connection.cursor(DictCursor) as cursor:
                sql_parents = """
                SELECT 
                    sc.id, 
                    tv10.value as z_num,
                    tv12.value as z_data_r
                FROM modx_site_content sc 
                INNER JOIN modx_site_tmplvar_contentvalues tv6 
                    ON tv6.contentid = sc.id AND tv6.tmplvarid = 6 
                    AND tv6.value = 'Закон Севастополя'
                INNER JOIN modx_site_tmplvar_contentvalues tv10 
                    ON tv10.contentid = sc.id AND tv10.tmplvarid = 10
                LEFT JOIN modx_site_tmplvar_contentvalues tv12 
                    ON tv12.contentid = sc.id AND tv12.tmplvarid = 12
                WHERE sc.deleted = 0 
                  AND sc.published = 1
                  AND sc.template = 103
                  AND tv10.value = %s
                """
                law_num = law_number.strip()
                if not law_num.endswith('-ЗС'):
                    law_num = f"{law_num}-ЗС"
                cursor.execute(sql_parents, (law_num,))
                parents = cursor.fetchall()
                if not parents:
                    return []
                parent_ids = [str(parent['id']) for parent in parents]
                sql_children = f"""
                SELECT id, pagetitle, content, parent
                FROM modx_site_content 
                WHERE deleted = 0 
                  AND published = 1
                  AND parent IN ({','.join(['%s']*len(parent_ids))})
                  AND pagetitle LIKE %s
                """
                cursor.execute(sql_children, parent_ids + ['Текст Закона%'])
                children = cursor.fetchall()
                resources_data = []
                for child in children:
                    parent = next((p for p in parents if p['id'] == child['parent']), None)
                    if parent:
                        child_resource = {
                            'id': child['id'],
                            'pagetitle': child['pagetitle'],
                            'content': child['content'],
                            'parent': child['parent'],
                            'template': 12,
                            'z_num': parent.get('z_num', ''),
                            'z_data_r': parent.get('z_data_r', ''),
                            'z_vid': 'Закон Севастополя'
                        }
                        resources_data.append(child_resource)
                return resources_data
        except Exception as e:
            return []
        finally:
            if connection:
                self.release_db_connection(connection)

    def get_resources_by_resolution_number(self, resolution_number):
        connection = self.get_db_connection()
        try:
            with connection.cursor(DictCursor) as cursor:
                sql_parents = """
                SELECT 
                    sc.id, 
                    tv10.value as z_num,
                    tv12.value as z_data_r
                FROM modx_site_content sc 
                INNER JOIN modx_site_tmplvar_contentvalues tv6 
                    ON tv6.contentid = sc.id AND tv6.tmplvarid = 6 
                    AND tv6.value = 'Постановление ЗС Севастополя'
                INNER JOIN modx_site_tmplvar_contentvalues tv10 
                    ON tv10.contentid = sc.id AND tv10.tmplvarid = 10
                LEFT JOIN modx_site_tmplvar_contentvalues tv12 
                    ON tv12.contentid = sc.id AND tv12.tmplvarid = 12
                WHERE sc.deleted = 0 
                  AND sc.published = 1
                  AND sc.template = 103
                  AND tv10.value = %s
                """
                cursor.execute(sql_parents, (resolution_number,))
                parents = cursor.fetchall()
                if not parents:
                    return []
                parent_ids = [str(parent['id']) for parent in parents]
                sql_children = f"""
                SELECT id, pagetitle, content, parent
                FROM modx_site_content 
                WHERE deleted = 0 
                  AND published = 1
                  AND parent IN ({','.join(['%s']*len(parent_ids))})
                  AND pagetitle LIKE %s
                """
                cursor.execute(sql_children, parent_ids + ['Текст Постановления%'])
                children = cursor.fetchall()
                resources_data = []
                for child in children:
                    parent = next((p for p in parents if p['id'] == child['parent']), None)
                    if parent:
                        child_resource = {
                            'id': child['id'],
                            'pagetitle': child['pagetitle'],
                            'content': child['content'],
                            'parent': child['parent'],
                            'template': 12,
                            'z_num': parent.get('z_num', ''),
                            'z_data_r': parent.get('z_data_r', ''),
                            'z_vid': 'Постановление ЗС Севастополя'
                        }
                        resources_data.append(child_resource)
                return resources_data
        except Exception as e:
            return []
        finally:
            if connection:
                self.release_db_connection(connection)

    def _format_resources_list(self, resources_data, doc_type=None):
        all_resources = []
        for res in resources_data:
            if doc_type:
                doc_type_actual = doc_type
            else:
                doc_type_actual = 'law' if res.get('z_vid', '').startswith('Закон') else 'regulation'
            year = None
            if res.get('z_data_r'):
                year_match = re.search(r'\b(\d{4})\b', str(res['z_data_r']))
                if year_match and 1900 <= int(year_match.group(1)) <= 2100:
                    year = year_match.group(1)
            doc_num = res.get('z_num', 'без номера')
            doc_type_display = 'Закон' if doc_type_actual == 'law' else 'Постановление'
            all_resources.append({
                'id': res['id'],
                'display_text': f"{doc_type_display} № {doc_num}",
                'pagetitle': res.get('pagetitle', ''),
                'content': res.get('content', ''),
                'z_num': doc_num,
                'year': year,
                'doc_type': doc_type_actual,
                'parent_id': res.get('parent'),
                'template': res.get('template', 12)
            })
        return all_resources

    def get_resource_with_params_fast(self, resource_id):
        connection = self.get_db_connection()
        try:
            with connection.cursor(DictCursor) as cursor:
                sql = f"""
                SELECT 
                    sc.id, 
                    sc.pagetitle, 
                    sc.content, 
                    sc.parent,
                    sc.template,
                    MAX(CASE WHEN tv.tmplvarid = 6 THEN tv.value END) as z_vid,
                    MAX(CASE WHEN tv.tmplvarid = 8 THEN tv.value END) as z_author,
                    MAX(CASE WHEN tv.tmplvarid = 10 THEN tv.value END) as z_num,
                    MAX(CASE WHEN tv.tmplvarid = 11 THEN tv.value END) as z_data_v,
                    MAX(CASE WHEN tv.tmplvarid = 12 THEN tv.value END) as z_data_r,
                    MAX(CASE WHEN tv.tmplvarid = 74 THEN tv.value END) as z_data_p,
                    MAX(CASE WHEN tv.tmplvarid = 104 THEN tv.value END) as z_komitet,
                    MAX(CASE WHEN tv.tmplvarid = 105 THEN tv.value END) as z_data_pg,
                    MAX(CASE WHEN tv.tmplvarid = 108 THEN tv.value END) as z_data_1cht,
                    MAX(CASE WHEN tv.tmplvarid = 163 THEN tv.value END) as z_data_cons,
                    MAX(CASE WHEN tv.tmplvarid = 170 THEN tv.value END) as appendix_structure
                FROM modx_site_content sc 
                LEFT JOIN modx_site_tmplvar_contentvalues tv 
                    ON tv.contentid = sc.id AND tv.tmplvarid IN (6,8,10,11,12,74,104,105,108,163,170)
                WHERE sc.id = %s 
                AND sc.deleted = 0 
                GROUP BY sc.id, sc.pagetitle, sc.content, sc.parent, sc.template
                """
                cursor.execute(sql, (resource_id,))
                result = cursor.fetchone()
                if not result:
                    raise Exception(f"Ресурс {resource_id} не найден")
                return result
        finally:
            if connection:
                self.release_db_connection(connection)

    def get_parent_resource_params(self, parent_id):
        if not parent_id:
            return None
        connection = self.get_db_connection()
        try:
            with connection.cursor(DictCursor) as cursor:
                sql = f"""
                SELECT 
                    tv6.value as z_vid,
                    tv8.value as z_author,
                    tv10.value as z_num,
                    tv11.value as z_data_v,
                    tv12.value as z_data_r,
                    tv74.value as z_data_p,
                    tv104.value as z_komitet,
                    tv105.value as z_data_pg,
                    tv108.value as z_data_1cht,
                    tv163.value as z_data_cons,
                    tv170.value as appendix_structure
                FROM modx_site_tmplvar_contentvalues tv6 
                LEFT JOIN modx_site_tmplvar_contentvalues tv8 ON tv8.contentid = %s AND tv8.tmplvarid = 8
                LEFT JOIN modx_site_tmplvar_contentvalues tv10 ON tv10.contentid = %s AND tv10.tmplvarid = 10
                LEFT JOIN modx_site_tmplvar_contentvalues tv11 ON tv11.contentid = %s AND tv11.tmplvarid = 11
                LEFT JOIN modx_site_tmplvar_contentvalues tv12 ON tv12.contentid = %s AND tv12.tmplvarid = 12
                LEFT JOIN modx_site_tmplvar_contentvalues tv74 ON tv74.contentid = %s AND tv74.tmplvarid = 74
                LEFT JOIN modx_site_tmplvar_contentvalues tv104 ON tv104.contentid = %s AND tv104.tmplvarid = 104
                LEFT JOIN modx_site_tmplvar_contentvalues tv105 ON tv105.contentid = %s AND tv105.tmplvarid = 105
                LEFT JOIN modx_site_tmplvar_contentvalues tv108 ON tv108.contentid = %s AND tv108.tmplvarid = 108
                LEFT JOIN modx_site_tmplvar_contentvalues tv163 ON tv163.contentid = %s AND tv163.tmplvarid = 163
                LEFT JOIN modx_site_tmplvar_contentvalues tv170 ON tv170.contentid = %s AND tv170.tmplvarid = 170
                WHERE tv6.contentid = %s AND tv6.tmplvarid = 6
                """
                cursor.execute(sql, (parent_id, parent_id, parent_id, parent_id, parent_id, parent_id, parent_id, parent_id, parent_id, parent_id, parent_id))
                parent_data = cursor.fetchone()
                if not parent_data:
                    sql_direct = f"""
                    SELECT 
                        sc.id,
                        tv6.value as z_vid,
                        tv8.value as z_author,
                        tv10.value as z_num,
                        tv11.value as z_data_v,
                        tv12.value as z_data_r,
                        tv74.value as z_data_p,
                        tv104.value as z_komitet,
                        tv105.value as z_data_pg,
                        tv108.value as z_data_1cht,
                        tv163.value as z_data_cons,
                        tv170.value as appendix_structure
                    FROM modx_site_content sc
                    LEFT JOIN modx_site_tmplvar_contentvalues tv6 ON tv6.contentid = sc.id AND tv6.tmplvarid = 6
                    LEFT JOIN modx_site_tmplvar_contentvalues tv8 ON tv8.contentid = sc.id AND tv8.tmplvarid = 8
                    LEFT JOIN modx_site_tmplvar_contentvalues tv10 ON tv10.contentid = sc.id AND tv10.tmplvarid = 10
                    LEFT JOIN modx_site_tmplvar_contentvalues tv11 ON tv11.contentid = sc.id AND tv11.tmplvarid = 11
                    LEFT JOIN modx_site_tmplvar_contentvalues tv12 ON tv12.contentid = sc.id AND tv12.tmplvarid = 12
                    LEFT JOIN modx_site_tmplvar_contentvalues tv74 ON tv74.contentid = sc.id AND tv74.tmplvarid = 74
                    LEFT JOIN modx_site_tmplvar_contentvalues tv104 ON tv104.contentid = sc.id AND tv104.tmplvarid = 104
                    LEFT JOIN modx_site_tmplvar_contentvalues tv105 ON tv105.contentid = sc.id AND tv105.tmplvarid = 105
                    LEFT JOIN modx_site_tmplvar_contentvalues tv108 ON tv108.contentid = sc.id AND tv108.tmplvarid = 108
                    LEFT JOIN modx_site_tmplvar_contentvalues tv163 ON tv163.contentid = sc.id AND tv163.tmplvarid = 163
                    LEFT JOIN modx_site_tmplvar_contentvalues tv170 ON tv170.contentid = sc.id AND tv170.tmplvarid = 170
                    WHERE sc.id = %s AND sc.deleted = 0
                    """
                    cursor.execute(sql_direct, (parent_id,))
                    parent_data = cursor.fetchone()
                return parent_data
        except Exception as e:
            return None
        finally:
            if connection:
                self.release_db_connection(connection)

    def get_first_child_publish_tv(self, container_id):
        connection = self.get_db_connection()
        try:
            with connection.cursor(DictCursor) as cursor:
                sql = """
                SELECT sc.id
                FROM modx_site_content sc
                WHERE sc.parent = %s
                  AND sc.deleted = 0
                  AND sc.published = 1
                ORDER BY sc.menuindex ASC
                LIMIT 1
                """
                cursor.execute(sql, (container_id,))
                child = cursor.fetchone()
                if not child:
                    return None
                child_id = child['id']
                sql_tv = """
                SELECT value
                FROM modx_site_tmplvar_contentvalues
                WHERE contentid = %s AND tmplvarid = 64
                """
                cursor.execute(sql_tv, (child_id,))
                tv = cursor.fetchone()
                return tv['value'] if tv else None
        except Exception as e:
            return None
        finally:
            if connection:
                self.release_db_connection(connection)

    def connect_ssh(self):
        import time
        max_retries = 2
        retry_delay = 3
        for attempt in range(max_retries):
            try:
                self.ssh = paramiko.SSHClient()
                known_hosts = os.path.expanduser('~/.ssh/known_hosts')
                if os.path.exists(known_hosts):
                    self.ssh.load_system_host_keys()
                    self.ssh.load_host_keys(known_hosts)
                self.ssh.set_missing_host_key_policy(paramiko.RejectPolicy())
                ssh_kwargs = {
                    'hostname': self.ssh_host,
                    'port': self.ssh_port,
                    'username': self.ssh_username,
                    'password': self.ssh_password,
                    'timeout': 30,
                    'banner_timeout': 30,
                    'auth_timeout': 30,
                }
                if sys.platform == 'win32':
                    ssh_kwargs['allow_agent'] = False
                    ssh_kwargs['look_for_keys'] = False
                self.ssh.connect(**ssh_kwargs)
                stdin, stdout, stderr = self.ssh.exec_command('echo "SSH_OK"', timeout=10)
                output = stdout.read().decode().strip()
                if output == "SSH_OK":
                    self.sftp = self.ssh.open_sftp()
                    return True
                else:
                    raise Exception(f"Ошибка тестирования SSH: {output}")
            except Exception as e:
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
                    continue
                else:
                    raise Exception(f"Не удалось подключиться по SSH после {max_retries} попыток: {e}")
        return False

    def execute_ssh_command(self, command, timeout=30):
        try:
            stdin, stdout, stderr = self.ssh.exec_command(command, timeout=timeout)
            output = stdout.read().decode('utf-8', errors='ignore').strip()
            error = stderr.read().decode('utf-8', errors='ignore').strip()
            return output, error
        except Exception as e:
            raise Exception(f"Ошибка выполнения SSH команды: {e}")

    def create_structure(self, doc_type, year):
        if doc_type == 'law':
            doc_path = 'law'
        else:
            doc_path = 'resolution'
        paths = [
            f"{self.base_path}/assets/json",
            f"{self.base_path}/assets/json/{doc_path}",
            f"{self.base_path}/assets/json/{doc_path}/{year}"
        ]
        for path in paths:
            cmd_check = f"if [ -d {shlex.quote(path)} ]; then echo 'exists'; else echo 'not_exists'; fi"
            output, error = self.execute_ssh_command(cmd_check, timeout=10)
            if output != 'exists':
                cmd_create = f"mkdir -p {shlex.quote(path)}"
                output, error = self.execute_ssh_command(cmd_create, timeout=10)
                if error:
                    raise Exception(f"Ошибка создания {path}: {error}")
                cmd_chmod = f"chmod 755 {shlex.quote(path)}"
                self.execute_ssh_command(cmd_chmod, timeout=10)
        return True

    def upload_json_via_sftp(self, resource_id, year, json_data, doc_type):
        if doc_type == 'law':
            relative_path = f"/assets/json/law/{year}/{resource_id}.json"
        else:
            relative_path = f"/assets/json/resolution/{year}/{resource_id}.json"
        full_path = f"{self.base_path}{relative_path}"
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False, encoding='utf-8') as tmp_file:
            json.dump(json_data, tmp_file, ensure_ascii=False, indent=2)
            tmp_path = tmp_file.name
        try:
            self.sftp.put(tmp_path, full_path)
            cmd_chmod = f"chmod 644 {shlex.quote(full_path)}"
            self.execute_ssh_command(cmd_chmod)
            return relative_path
        except Exception as e:
            raise Exception(f"Ошибка при загрузке через SFTP: {e}")
        finally:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass

    def update_tv_parameter(self, resource_id, tv_value):
        connection = self.get_db_connection()
        try:
            with connection.cursor(DictCursor) as cursor:
                sql_check = "SELECT value FROM modx_site_tmplvar_contentvalues WHERE contentid = %s AND tmplvarid = 172"
                cursor.execute(sql_check, (resource_id,))
                existing = cursor.fetchone()
                if existing:
                    sql_update = "UPDATE modx_site_tmplvar_contentvalues SET value = %s WHERE contentid = %s AND tmplvarid = 172"
                    cursor.execute(sql_update, (tv_value, resource_id))
                else:
                    sql_insert = "INSERT INTO modx_site_tmplvar_contentvalues (tmplvarid, contentid, value) VALUES (172, %s, %s)"
                    cursor.execute(sql_insert, (resource_id, tv_value))
                connection.commit()
                return True
        except Exception as e:
            connection.rollback()
            raise Exception(f"Ошибка при обновлении TV параметра: {e}")
        finally:
            if connection:
                self.release_db_connection(connection)


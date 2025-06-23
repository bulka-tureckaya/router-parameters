import pywifi
from pywifi import const
import time
import psycopg2
from psycopg2 import sql
import logging
from logging.handlers import RotatingFileHandler
import os
import uuid
from datetime import datetime
import sys
from dotenv import load_dotenv

load_dotenv()

def get_db_config():
    return {
        'dbname': os.getenv('DB_NAME'),
        'user': os.getenv('DB_USER'),
        'password': os.getenv('DB_PASSWORD'),
        'host': os.getenv('DB_HOST')
    }

def setup_logging():
    log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'log')
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)
    
    log_file = os.path.join(log_dir, 'wifi_scanner.log')
    
    logger = logging.getLogger('wifi_scanner')
    logger.setLevel(logging.INFO)
    
    handler = RotatingFileHandler(
        log_file, maxBytes=10*1024*1024, backupCount=5, encoding='utf-8'
    )
    formatter = logging.Formatter(
        '%(asctime)s - %(levelname)s - %(message)s'
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    
    return logger

logger = setup_logging()

def get_db_connection():
    try:
        config = get_db_config()
        conn = psycopg2.connect(**config)
        conn.cursor().execute("SET SESSION uuid.enable = 'on';")
        return conn
    except Exception as e:
        logger.error(f"Ошибка подключения к PostgreSQL: {e}")
        raise

def save_network_to_db(conn, network_data):
    try:
        with conn.cursor() as cursor:
            record_id = str(uuid.uuid4())
            
            query = sql.SQL("""
                INSERT INTO networks (
                    id, ssid, bssid, signal_dbm, channel, 
                    frequency, encryption, authentication
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """)
            
            cursor.execute(query, (
                record_id,
                network_data['ssid'],
                network_data['bssid'],
                network_data['signal'],
                network_data['channel'] if network_data['channel'] is not None else None,
                network_data['frequency'],
                network_data['encryption'],
                network_data['authentication']
            ))
            
            conn.commit()
            logger.info(f"Сохранена сеть: {network_data['bssid']} с ID {record_id}")
            
    except psycopg2.Error as e:
        conn.rollback()
        logger.error(f"Ошибка PostgreSQL при сохранении сети {network_data['bssid']}: {e.pgerror}")
    except Exception as e:
        conn.rollback()
        logger.error(f"Общая ошибка при сохранении сети {network_data['bssid']}: {str(e)}")

def clean_old_records(conn, max_records=1000):
    """Удаляет самые старые записи, если общее количество превышает max_records"""
    try:
        with conn.cursor() as cursor:
            # Получаем текущее количество записей
            cursor.execute("SELECT COUNT(*) FROM networks")
            count = cursor.fetchone()[0]
            
            if count > max_records:
                to_delete = count - max_records
                logger.info(f"Найдено {count} записей. Удаляем {to_delete} самых старых.")
                
                # Удаляем самые старые записи
                cursor.execute("""
                    DELETE FROM networks 
                    WHERE id IN (
                        SELECT id FROM networks 
                        ORDER BY scan_time ASC 
                        LIMIT %s
                    )
                """, (to_delete,))
                
                conn.commit()
                logger.info(f"Удалено {to_delete} старых записей. Осталось {max_records} записей.")
            else:
                logger.info(f"В базе {count} записей. Лимит не превышен.")
                
    except Exception as e:
        conn.rollback()
        logger.error(f"Ошибка при очистке старых записей: {str(e)}")


def scan_wifi_networks():
    try:
        logger.info("Начало сканирования Wi-Fi сетей")
        
        wifi = pywifi.PyWiFi()
        if len(wifi.interfaces()) == 0:
            logger.error("Нет доступных Wi-Fi интерфейсов!")
            return
        
        iface = wifi.interfaces()[0]
        
        if iface.status() in [const.IFACE_DISCONNECTED, const.IFACE_INACTIVE]:
            iface.disconnect()
            time.sleep(1)
        
        logger.info(f"Используется интерфейс: {iface.name()}")
        
        iface.scan()
        time.sleep(5)
        results = iface.scan_results()
        
        if not results:
            logger.warning("Не найдено доступных Wi-Fi сетей.")
            return
        
        conn = get_db_connection()
        
        for network in results:
            # Определяем частоту и канал
            freq = network.freq / 1000
            if 2412 <= network.freq <= 2484:
                channel = (network.freq - 2412) // 5 + 1
            elif network.freq == 2484:
                channel = 14
            elif 5170 <= network.freq <= 5825:
                channel = (network.freq - 5170) // 5 + 34
            else:
                channel = None
            
            # Определяем тип аутентификации
            akm_types = []
            for akm in network.akm:
                if akm == const.AKM_TYPE_NONE:
                    akm_types.append("None")
                elif akm == const.AKM_TYPE_WPA:
                    akm_types.append("WPA")
                elif akm == const.AKM_TYPE_WPAPSK:
                    akm_types.append("WPA-PSK")
                elif akm == const.AKM_TYPE_WPA2:
                    akm_types.append("WPA2")
                elif akm == const.AKM_TYPE_WPA2PSK:
                    akm_types.append("WPA2-PSK")
                elif akm == const.AKM_TYPE_UNKNOWN:
                    akm_types.append("Unknown")
            
            network_data = {
                'ssid': network.ssid if network.ssid else 'Hidden',
                'bssid': network.bssid,
                'signal': network.signal,
                'channel': channel,
                'frequency': freq,
                'encryption': 'Open' if network.akm == [0] else 'Secured',
                'authentication': ', '.join(akm_types) if akm_types else 'Unknown'
            }
            
            save_network_to_db(conn, network_data)
        
        clean_old_records(conn, max_records=1000)

        conn.close()
        logger.info(f"Сканирование завершено успешно. Найдено сетей: {len(results)}")
        
    except Exception as e:
        logger.error(f"Ошибка при сканировании: {str(e)}", exc_info=True)

if __name__ == "__main__":
    try:
        scan_wifi_networks()
    except Exception as e:
        logger.critical(f"Критическая ошибка: {str(e)}", exc_info=True)
        sys.exit(1)

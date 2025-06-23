# WiFi Network Scanner & Analyzer

## Описание проекта
Система для мониторинга Wi-Fi сетей с автоматическим сбором параметров, хранением в PostgreSQL и визуализацией в Grafana. Особенность - партицирование данных по часам для оптимального хранения и быстрого доступа.

## Основные функции
- Сканирование доступных Wi-Fi сетей
- Запись параметров (SSID, BSSID, уровень сигнала, канал, тип шифрования)
- Автоматическая очистка старых записей (по умолчанию сохраняется 10000 последних записей)
- Логирование всех операций
- Интеграция с Grafana для визуализации данных

## Установка зависимостей
```bash
pip install pywifi psycopg2-binary python-dotenv
```
## Настройка окружения
1. Создайте файл .env в корне проекта:
```
DB_NAME=db_name
DB_USER=your_user
DB_PASSWORD=your_password
DB_HOST=localhost
```
2. Настройте PostgreSQL (создайте БД и пользователя)

## Запуск
### Ручной запуск
```
# Для windows
python wifi.py

# Для linux
python3 wifi.py
```
### Автоматический запуск через cron (Linux/WSL)
```bash
* * * * * /path/to/venv/bin/python /path/to/project/wifi.py >> /path/to/project/log/cron.log 2>&1
```
### Планировщик задач (Windows)
1. Создайте BAT-файл:
```bat
@echo off
C:\path\to\venv\Scripts\python.exe C:\path\to\project\wifi.py >> C:\path\to\project\log\cron.log 2>&1
```
2. Настройте задание в Планировщике задач с триггером "Ежедневно" и повторением каждую минуту.
## Визуализация в Grafana
Пример дашборда для отображения:
- График уровня сигнала по времени
![image](https://github.com/user-attachments/assets/2e774435-9dd7-4436-87fd-7cff6e2ec8c5)

- Топ-5 сетей по силе сигнала
![image](https://github.com/user-attachments/assets/f5f1fefa-1d34-4508-889d-5e3dd8b10871)

- Распределение сетей по каналам
![image](https://github.com/user-attachments/assets/d733107e-0788-4c8c-9299-dab3c1afdb91)

## База данных
Создание партицированной таблицы:
```sql
-- Основная таблица
CREATE TABLE networks (
    id UUID DEFAULT gen_random_uuid(),
    scan_time TIMESTAMP NOT NULL,
    ssid TEXT,
    bssid TEXT,
    signal_dbm INTEGER,
    channel INTEGER,
    frequency FLOAT,
    encryption TEXT,
    authentication TEXT
) PARTITION BY RANGE (scan_time);

-- Функция для автоматического создания партиций
CREATE OR REPLACE FUNCTION create_network_partition()
RETURNS TRIGGER AS $$
DECLARE
    partition_name TEXT;
    from_time TEXT;
    to_time TEXT;
BEGIN
    partition_name := 'networks_' || to_char(NEW.scan_time, 'YYYYMMDD_HH24');
    from_time := to_char(NEW.scan_time, 'YYYY-MM-DD HH24:00:00');
    to_time := to_char(NEW.scan_time + interval '1 hour', 'YYYY-MM-DD HH24:00:00');
    
    IF NOT EXISTS (SELECT 1 FROM pg_tables WHERE tablename = partition_name) THEN
        EXECUTE format('CREATE TABLE %I PARTITION OF networks FOR VALUES FROM (%L) TO (%L)',
                      partition_name, from_time, to_time);
    END IF;
    
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Триггер для автоматического создания партиций
CREATE TRIGGER trg_network_partition
BEFORE INSERT ON networks
FOR EACH ROW EXECUTE FUNCTION create_network_partition();
```
Очистка старых партиций старше 24 часов:
1. Для Linux/WSL (через cron):
```bash
0 0 * * * psql -U your_user -d db_name -c "SELECT drop_old_network_partitions();" >> /path/to/project/log/partition_clean.log 2>&1
```
2. Для Windows (через Планировщик задач):
Создайте файл clean_partitions.bat:
```bat
@echo off
"C:\Program Files\PostgreSQL\15\bin\psql.exe" -U your_user -d db_name -c "SELECT drop_old_network_partitions();" >> C:\path\to\project\log\partition_clean.log 2>&1
```
Настройте ежедневное выполнение в 00:00.

Функция очистки:
```
CREATE OR REPLACE FUNCTION drop_old_network_partitions()
RETURNS void AS $$
DECLARE
    partition_name text;
BEGIN
    FOR partition_name IN
        SELECT tablename 
        FROM pg_tables 
        WHERE tablename LIKE 'networks\_%' ESCAPE '\'
        AND tablename < 'networks_' || to_char(NOW() - interval '24 hours', 'YYYYMMDD_HH24')
    LOOP
        EXECUTE format('DROP TABLE %I', partition_name);
        RAISE NOTICE 'Удалена партиция: %', partition_name;
    END LOOP;
END;
$$ LANGUAGE plpgsql;
```

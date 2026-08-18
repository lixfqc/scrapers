# -*- coding: utf-8 -*-
"""
爱尔兰 IE 爬虫 - CSO TEM28（New Private Cars Licensed for the First Time）
- 数据源: CSO 中央统计局 PxStat API
- URL: https://ws.cso.ie/public/api.restful/PxStat.Data.Cube_API.ReadDataset/TEM28/CSV/1.0/en
- 粒度: 车型级（Make and Model）+ 8种燃料，2024-01 起，月度
- 口径: 首次注册（Licensed for the First Time）= 新注册
"""
import sys
import io
import csv
import re
import logging
import random
import requests
from datetime import date, datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from base_crawler import BaseCrawler, DB_CONFIG, UA_LIST

logger = logging.getLogger(__name__)

IE_TEM28_URL = ('https://ws.cso.ie/public/api.restful/'
                'PxStat.Data.Cube_API.ReadDataset/TEM28/CSV/1.0/en')

# 品牌码前3位 → 品牌规范名（从车型代码映射，避免车型名首词噪音如 MIN=Countryman）
IE_BRAND_CODE_MAP = {
    'ALF': 'Alfa Romeo', 'AUD': 'Audi', 'BMW': 'BMW', 'BYD': 'BYD',
    'CIT': 'Citroen', 'CRP': 'Cupra', 'DAC': 'Dacia', 'FIA': 'Fiat',
    'FOR': 'Ford', 'HON': 'Honda', 'HYU': 'Hyundai', 'JAG': 'Jaguar',
    'JEE': 'Jeep', 'KIA': 'Kia', 'LAR': 'Land Rover', 'LEP': 'Leapmotor',
    'LEX': 'Lexus', 'MAZ': 'Mazda', 'MER': 'Mercedes-Benz', 'MGA': 'MG',
    'MIN': 'Mini', 'MIT': 'Mitsubishi', 'NIS': 'Nissan', 'OPE': 'Opel',
    'PEU': 'Peugeot', 'POR': 'Porsche', 'PSR': 'Polestar', 'REN': 'Renault',
    'SEA': 'Seat', 'SKO': 'Skoda', 'SMA': 'Smart', 'SSA': 'Ssangyong',
    'SUB': 'Subaru', 'SUZ': 'Suzuki', 'TES': 'Tesla', 'TOY': 'Toyota',
    'VOL': 'Volkswagen', 'VOO': 'Volvo', 'XNG': 'Xpeng',
    # ZZZ 是汇总行（All models/Other），跳过不入库
}

# 燃料 → 标准 energy_type
IE_FUEL_MAP = {
    'Petrol': 'GASOLINE',
    'Diesel': 'DIESEL',
    'Electric': 'BEV',
    'Petrol and electric hybrid': 'HEV',
    'Diesel and electric hybrid': 'HEV',
    'Petrol or Diesel plug-in hybrid electric': 'PHEV',
    'Other fuel types': 'OTHER',
    'All fuel types': None,  # 汇总行：能源维度None（仅入库品牌×车型级，不入All）
}

SKIP_BRAND_CODES = {'ZZZ'}  # All models / Other 汇总行


class IeCrawler(BaseCrawler):
    """爱尔兰 CSO TEM28 爬虫"""

    def __init__(self):
        super().__init__(source_name='ie_cso_tem28', country_code='IE')
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': random.choice(UA_LIST),
            'Accept': 'text/csv,text/html,*/*;q=0.8',
        })
        self._brand_id_cache = {}

    def latest_available_month(self):
        """下载CSV，扫描最后一行的 TLIST(M1) 作为最新月"""
        resp = self.retry_request(self.session.get, IE_TEM28_URL, timeout=120)
        if resp is None:
            return None
        content = resp.content
        max_ym = None
        for line in content.decode('utf-8-sig', errors='ignore').splitlines()[-500:]:
            parts = self._csv_split(line)
            if len(parts) < 4:
                continue
            ym = parts[2].strip()
            if re.fullmatch(r'\d{6}', ym):
                y, m = int(ym[:4]), int(ym[4:])
                if max_ym is None or (y, m) > max_ym:
                    max_ym = (y, m)
        return max_ym

    def download_csv(self):
        resp = self.retry_request(self.session.get, IE_TEM28_URL, timeout=180)
        if resp is None:
            return None
        return resp.content

    @staticmethod
    def _csv_split(line):
        """简易CSV行解析（TEM28字段少，逗号分隔，字段可能含引号）"""
        return list(csv.reader([line]))[0]

    def parse_csv(self, content):
        """解析全量CSV → records列表（车型级，能源维度）
        只入库非All fuel types的行（车型×燃料），brand=品牌码映射名
        """
        records = []
        text = content.decode('utf-8-sig', errors='ignore')
        lines = text.splitlines()
        if not lines:
            return records
        header = self._csv_split(lines[0])
        try:
            i_ym = header.index('TLIST(M1)')
            i_fuel = header.index('Type of Fuel')
            i_model = header.index('Make and Model')
            i_val = header.index('VALUE')
        except ValueError as e:
            logger.error('IE CSV表头异常: %s', e)
            return records

        for line in lines[1:]:
            parts = self._csv_split(line)
            if len(parts) <= i_val:
                continue
            ym = parts[i_ym].strip()
            if not re.fullmatch(r'\d{6}', ym):
                continue
            fuel_raw = parts[i_fuel].strip()
            model_raw = parts[i_model].strip()
            code = parts[6].strip() if len(parts) > 6 else ''
            val_raw = parts[i_val].strip()
            if not val_raw:
                continue
            try:
                val = int(val_raw)
            except ValueError:
                continue
            if val <= 0:
                continue
            bcode = code[:3]
            if bcode in SKIP_BRAND_CODES:
                continue  # All models / Other 汇总行
            brand = IE_BRAND_CODE_MAP.get(bcode)
            if not brand:
                continue
            if not model_raw:
                continue
            energy = IE_FUEL_MAP.get(fuel_raw, 'OTHER')
            if energy is None:
                continue  # All fuel types 汇总行不入库
            year = int(ym[:4])
            month = int(ym[4:])
            records.append({
                'country_code': 'IE',
                'source_month': date(year, month, 1),
                'brand_name_raw': brand,
                'brand_id': None,
                'model_name': model_raw,
                'vehicle_type': 'passenger',
                'energy_type': energy,
                'segment': None,
                'raw_unit': 'units',
                'sales_volume_raw': val,
                'sales_volume_normalized': val,
                'revision_no': 1,
                'is_latest': True,
                'pub_date': None,
                'crawl_time': datetime.now(),
                'data_source': 'ie_cso_tem28',
                'notes': 'CSO TEM28 new private cars licensed first time (model x fuel)',
            })
        return records

    def get_brand_id(self, brand_name_raw):
        """品牌匹配：UPPER查canonical_name/brand_name_cn → variant回退"""
        lookup = brand_name_raw.upper().strip()
        if lookup in self._brand_id_cache:
            return self._brand_id_cache[lookup]
        conn, cur = self.get_connection()
        cur.execute(
            "SELECT id FROM brand_name_mapping "
            "WHERE UPPER(canonical_name)=%s OR UPPER(brand_name_cn)=%s LIMIT 1",
            (lookup, lookup))
        row = cur.fetchone()
        if row:
            self._brand_id_cache[lookup] = row['id']
            return row['id']
        cur.execute(
            "SELECT brand_id FROM brand_name_variant WHERE UPPER(variant_name)=%s LIMIT 1",
            (lookup,))
        row = cur.fetchone()
        bid = row['brand_id'] if row else None
        self._brand_id_cache[lookup] = bid
        return bid

    def save_sales(self, record):
        record['brand_id'] = self.get_brand_id(record['brand_name_raw'])
        super().save_sales(record)

    def crawl_full(self):
        """全量下载解析入库"""
        content = self.download_csv()
        if content is None:
            return 0
        records = self.parse_csv(content)
        for rec in records:
            self.save_sales(rec)
        return len(records)

    def crawl_incremental(self):
        """增量：查库MAX(source_month)，只入库新月份"""
        max_month = self._get_db_max_month()
        latest = self.latest_available_month()
        if latest is None:
            return 0
        ly, lm = latest
        latest_date = date(ly, lm, 1)
        if max_month is not None and latest_date <= max_month:
            return 0
        return self.crawl_full()

    def _get_db_max_month(self):
        conn, cur = self.get_connection()
        cur.execute(
            "SELECT MAX(source_month) AS m FROM market_sales_monthly "
            "WHERE country_code='IE' AND data_source='ie_cso_tem28'")
        row = cur.fetchone()
        return row['m'] if row and row['m'] else None

    def main(self):
        n = self.crawl_incremental()
        print(f'IE incremental saved: {n}')
        return n


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    c = IeCrawler()
    c.main()

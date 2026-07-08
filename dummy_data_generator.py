#!/usr/bin/env python3
"""
Multi-Database Dummy Data Generator
Supports: MySQL, PostgreSQL, Oracle
Interactive CLI for schema inspection and dynamic data injection
"""

import sys
import json
from typing import Dict, List, Tuple, Any, Optional
from dataclasses import dataclass
from datetime import datetime, timedelta
from abc import ABC, abstractmethod
import random
import string
from faker import Faker

# Database drivers
try:
    import mysql.connector
    MYSQL_AVAILABLE = True
except ImportError:
    MYSQL_AVAILABLE = False

try:
    import psycopg2
    from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
    POSTGRES_AVAILABLE = True
except ImportError:
    POSTGRES_AVAILABLE = False

try:
    import cx_Oracle
    ORACLE_AVAILABLE = True
except ImportError:
    ORACLE_AVAILABLE = False


fake = Faker()


@dataclass
class ColumnInfo:
    """Column metadata"""
    name: str
    data_type: str
    nullable: bool
    is_pk: bool
    is_fk: bool
    fk_table: Optional[str] = None
    fk_column: Optional[str] = None
    is_unique: bool = False
    max_length: Optional[int] = None


class DatabaseConnector(ABC):
    """Abstract base for DB connections"""
    
    def __init__(self, connection_params: Dict[str, Any]):
        self.connection_params = connection_params
        self.conn = None
        self.cursor = None
    
    @abstractmethod
    def connect(self) -> bool:
        """Test connection"""
        pass
    
    @abstractmethod
    def get_columns(self, schema: str, table: str) -> List[ColumnInfo]:
        """Inspect table structure"""
        pass
    
    @abstractmethod
    def get_existing_pk_values(self, schema: str, table: str, pk_column: str) -> List[Any]:
        """Get existing PK values for FK reference"""
        pass
    
    @abstractmethod
    def batch_insert(self, schema: str, table: str, columns: List[str], rows: List[Tuple]) -> int:
        """Insert batch of rows"""
        pass
    
    @abstractmethod
    def close(self):
        """Close connection"""
        pass


class MySQLConnector(DatabaseConnector):
    """MySQL implementation"""
    
    def connect(self) -> bool:
        try:
            self.conn = mysql.connector.connect(
                host=self.connection_params.get('host', 'localhost'),
                port=self.connection_params.get('port', 3306),
                user=self.connection_params.get('user'),
                password=self.connection_params.get('password'),
                database=self.connection_params.get('database')
            )
            self.cursor = self.conn.cursor(dictionary=True)
            print("✓ MySQL connection successful")
            return True
        except Exception as e:
            print(f"✗ MySQL connection failed: {e}")
            return False
    
    def get_columns(self, schema: str, table: str) -> List[ColumnInfo]:
        """Query INFORMATION_SCHEMA for column metadata"""
        query = """
        SELECT 
            c.COLUMN_NAME,
            c.DATA_TYPE,
            c.IS_NULLABLE,
            IF(tc.COLUMN_NAME IS NOT NULL, 'PRI', 'NO') as KEY_TYPE,
            c.CHARACTER_MAXIMUM_LENGTH,
            kcu.REFERENCED_TABLE_NAME,
            kcu.REFERENCED_COLUMN_NAME
        FROM INFORMATION_SCHEMA.COLUMNS c
        LEFT JOIN INFORMATION_SCHEMA.TABLE_CONSTRAINTS tc 
            ON c.TABLE_SCHEMA = tc.TABLE_SCHEMA 
            AND c.TABLE_NAME = tc.TABLE_NAME 
            AND tc.CONSTRAINT_TYPE = 'PRIMARY KEY'
            AND c.COLUMN_NAME = tc.TABLE_NAME
        LEFT JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE kcu
            ON c.TABLE_SCHEMA = kcu.TABLE_SCHEMA
            AND c.TABLE_NAME = kcu.TABLE_NAME
            AND c.COLUMN_NAME = kcu.COLUMN_NAME
            AND kcu.REFERENCED_TABLE_NAME IS NOT NULL
        WHERE c.TABLE_SCHEMA = %s AND c.TABLE_NAME = %s
        ORDER BY c.ORDINAL_POSITION
        """
        
        self.cursor.execute(query, (schema, table))
        rows = self.cursor.fetchall()
        
        columns = []
        for row in rows:
            col = ColumnInfo(
                name=row['COLUMN_NAME'],
                data_type=row['DATA_TYPE'],
                nullable=row['IS_NULLABLE'] == 'YES',
                is_pk=row['KEY_TYPE'] == 'PRI',
                is_fk=row['REFERENCED_TABLE_NAME'] is not None,
                fk_table=row['REFERENCED_TABLE_NAME'],
                fk_column=row['REFERENCED_COLUMN_NAME'],
                max_length=row['CHARACTER_MAXIMUM_LENGTH']
            )
            columns.append(col)
        
        return columns
    
    def get_existing_pk_values(self, schema: str, table: str, pk_column: str) -> List[Any]:
        """Get existing PK values"""
        query = f"SELECT DISTINCT {pk_column} FROM {schema}.{table} LIMIT 1000"
        self.cursor.execute(query)
        return [row[pk_column] for row in self.cursor.fetchall()]
    
    def batch_insert(self, schema: str, table: str, columns: List[str], rows: List[Tuple]) -> int:
        """Batch insert with VALUES (...), (...), (...)"""
        if not rows:
            return 0
        
        col_str = ', '.join(columns)
        placeholders = ', '.join(['%s'] * len(columns))
        query = f"INSERT INTO {schema}.{table} ({col_str}) VALUES ({placeholders})"
        
        try:
            self.cursor.executemany(query, rows)
            self.conn.commit()
            return self.cursor.rowcount
        except Exception as e:
            self.conn.rollback()
            print(f"✗ Insert failed: {e}")
            raise
    
    def close(self):
        if self.cursor:
            self.cursor.close()
        if self.conn:
            self.conn.close()


class PostgreSQLConnector(DatabaseConnector):
    """PostgreSQL implementation"""
    
    def connect(self) -> bool:
        try:
            self.conn = psycopg2.connect(
                host=self.connection_params.get('host', 'localhost'),
                port=self.connection_params.get('port', 5432),
                user=self.connection_params.get('user'),
                password=self.connection_params.get('password'),
                database=self.connection_params.get('database')
            )
            self.conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
            self.cursor = self.conn.cursor()
            print("✓ PostgreSQL connection successful")
            return True
        except Exception as e:
            print(f"✗ PostgreSQL connection failed: {e}")
            return False
    
    def get_columns(self, schema: str, table: str) -> List[ColumnInfo]:
        """Query information_schema for column metadata"""
        query = """
        SELECT 
            c.column_name,
            c.data_type,
            c.is_nullable,
            tc.constraint_type,
            c.character_maximum_length,
            kcu.table_name as fk_table,
            kcu.column_name as fk_column
        FROM information_schema.columns c
        LEFT JOIN information_schema.constraint_column_usage ccu
            ON c.table_schema = ccu.table_schema
            AND c.table_name = ccu.table_name
            AND c.column_name = ccu.column_name
        LEFT JOIN information_schema.table_constraints tc
            ON ccu.table_schema = tc.table_schema
            AND ccu.table_name = tc.table_name
            AND ccu.constraint_name = tc.constraint_name
        LEFT JOIN information_schema.referential_constraints rc
            ON tc.constraint_schema = rc.constraint_schema
            AND tc.constraint_name = rc.constraint_name
        LEFT JOIN information_schema.key_column_usage kcu
            ON rc.unique_constraint_schema = kcu.constraint_schema
            AND rc.unique_constraint_name = kcu.constraint_name
        WHERE c.table_schema = %s AND c.table_name = %s
        ORDER BY c.ordinal_position
        """
        
        self.cursor.execute(query, (schema, table))
        rows = self.cursor.fetchall()
        
        columns = []
        for row in rows:
            col = ColumnInfo(
                name=row[0],
                data_type=row[1],
                nullable=row[2] == 'YES',
                is_pk=row[3] == 'PRIMARY KEY',
                is_fk=row[6] is not None,
                fk_table=row[5],
                fk_column=row[6],
                max_length=row[4]
            )
            columns.append(col)
        
        return columns
    
    def get_existing_pk_values(self, schema: str, table: str, pk_column: str) -> List[Any]:
        """Get existing PK values"""
        query = f"SELECT DISTINCT {pk_column} FROM {schema}.{table} LIMIT 1000"
        self.cursor.execute(query)
        return [row[0] for row in self.cursor.fetchall()]
    
    def batch_insert(self, schema: str, table: str, columns: List[str], rows: List[Tuple]) -> int:
        """Batch insert"""
        if not rows:
            return 0
        
        col_str = ', '.join(columns)
        placeholders = ', '.join(['%s'] * len(columns))
        query = f"INSERT INTO {schema}.{table} ({col_str}) VALUES ({placeholders})"
        
        try:
            for row in rows:
                self.cursor.execute(query, row)
            self.conn.commit()
            return len(rows)
        except Exception as e:
            self.conn.rollback()
            print(f"✗ Insert failed: {e}")
            raise
    
    def close(self):
        if self.cursor:
            self.cursor.close()
        if self.conn:
            self.conn.close()


class OracleConnector(DatabaseConnector):
    """Oracle implementation"""
    
    def connect(self) -> bool:
        try:
            dsn = cx_Oracle.makedsn(
                self.connection_params.get('host', 'localhost'),
                self.connection_params.get('port', 1521),
                service_name=self.connection_params.get('service_name', 'xe')
            )
            self.conn = cx_Oracle.connect(
                user=self.connection_params.get('user'),
                password=self.connection_params.get('password'),
                dsn=dsn
            )
            self.cursor = self.conn.cursor()
            print("✓ Oracle connection successful")
            return True
        except Exception as e:
            print(f"✗ Oracle connection failed: {e}")
            return False
    
    def get_columns(self, schema: str, table: str) -> List[ColumnInfo]:
        """Query ALL_TAB_COLUMNS and ALL_CONSTRAINTS"""
        query = """
        SELECT 
            atc.COLUMN_NAME,
            atc.DATA_TYPE,
            atc.NULLABLE,
            CASE WHEN acc.CONSTRAINT_TYPE = 'P' THEN 'PRI' ELSE 'NO' END as KEY_TYPE,
            atc.DATA_LENGTH,
            arc.TABLE_NAME as FK_TABLE,
            akcu.COLUMN_NAME as FK_COLUMN
        FROM ALL_TAB_COLUMNS atc
        LEFT JOIN ALL_CONS_COLUMNS acc
            ON atc.TABLE_NAME = acc.TABLE_NAME
            AND atc.COLUMN_NAME = acc.COLUMN_NAME
            AND atc.OWNER = acc.OWNER
        LEFT JOIN ALL_CONSTRAINTS ac
            ON acc.CONSTRAINT_NAME = ac.CONSTRAINT_NAME
            AND acc.OWNER = ac.OWNER
        LEFT JOIN ALL_CONSTRAINTS arc
            ON ac.R_CONSTRAINT_NAME = arc.CONSTRAINT_NAME
        LEFT JOIN ALL_CONS_COLUMNS akcu
            ON arc.CONSTRAINT_NAME = akcu.CONSTRAINT_NAME
            AND arc.OWNER = akcu.OWNER
        WHERE UPPER(atc.TABLE_NAME) = UPPER(:table)
            AND UPPER(atc.OWNER) = UPPER(:schema)
        ORDER BY atc.COLUMN_ID
        """
        
        self.cursor.execute(query, {'schema': schema, 'table': table})
        rows = self.cursor.fetchall()
        
        columns = []
        for row in rows:
            col = ColumnInfo(
                name=row[0],
                data_type=row[1],
                nullable=row[2] == 'Y',
                is_pk=row[3] == 'PRI',
                is_fk=row[5] is not None,
                fk_table=row[5],
                fk_column=row[6],
                max_length=row[4]
            )
            columns.append(col)
        
        return columns
    
    def get_existing_pk_values(self, schema: str, table: str, pk_column: str) -> List[Any]:
        """Get existing PK values"""
        query = f"SELECT DISTINCT {pk_column} FROM {schema}.{table} WHERE ROWNUM <= 1000"
        self.cursor.execute(query)
        return [row[0] for row in self.cursor.fetchall()]
    
    def batch_insert(self, schema: str, table: str, columns: List[str], rows: List[Tuple]) -> int:
        """Batch insert using INSERT ALL"""
        if not rows:
            return 0
        
        col_str = ', '.join(columns)
        try:
            for row in rows:
                placeholders = ', '.join([':' + str(i+1) for i in range(len(columns))])
                query = f"INSERT INTO {schema}.{table} ({col_str}) VALUES ({placeholders})"
                self.cursor.execute(query, row)
            self.conn.commit()
            return len(rows)
        except Exception as e:
            self.conn.rollback()
            print(f"✗ Insert failed: {e}")
            raise
    
    def close(self):
        if self.cursor:
            self.cursor.close()
        if self.conn:
            self.conn.close()


class DataGenerator:
    """Generate dummy data based on column type"""
    
    def __init__(self, connector: DatabaseConnector):
        self.connector = connector
        self.fk_cache = {}
    
    def generate_value(self, column: ColumnInfo) -> Any:
        """Generate single value based on data type"""
        data_type = column.data_type.upper()
        
        # Handle FK references
        if column.is_fk and column.fk_table:
            if column.fk_table not in self.fk_cache:
                # Load existing PK values
                self.fk_cache[column.fk_table] = self.connector.get_existing_pk_values(
                    '', column.fk_table, column.fk_column
                )
            
            if self.fk_cache[column.fk_table]:
                return random.choice(self.fk_cache[column.fk_table])
            else:
                return None
        
        # Skip PK (auto-increment)
        if column.is_pk:
            return None
        
        # Type-based generation
        if 'INT' in data_type or 'NUMBER' in data_type:
            return random.randint(1, 10000)
        
        elif 'FLOAT' in data_type or 'DOUBLE' in data_type or 'DECIMAL' in data_type:
            return round(random.uniform(10.0, 1000.0), 2)
        
        elif 'VARCHAR' in data_type or 'CHAR' in data_type or 'STRING' in data_type:
            max_len = min(column.max_length or 50, 100)
            if 'email' in column.name.lower():
                return fake.email()
            elif 'phone' in column.name.lower():
                return fake.phone_number()[:20]
            elif 'name' in column.name.lower():
                return fake.name()[:max_len]
            elif 'address' in column.name.lower():
                return fake.address()[:max_len]
            else:
                return fake.word()[:max_len]
        
        elif 'DATE' in data_type or 'TIMESTAMP' in data_type:
            days_offset = random.randint(-365, 0)
            return datetime.now() + timedelta(days=days_offset)
        
        elif 'BOOLEAN' in data_type or 'BOOL' in data_type:
            return random.choice([True, False])
        
        elif 'TEXT' in data_type:
            return fake.paragraph(nb_sentences=3)
        
        else:
            return None
    
    def generate_rows(self, columns: List[ColumnInfo], count: int) -> List[Tuple]:
        """Generate multiple rows"""
        rows = []
        filtered_cols = [c for c in columns if not c.is_pk]
        
        for _ in range(count):
            row = tuple(self.generate_value(col) for col in filtered_cols)
            rows.append(row)
        
        return rows, [c.name for c in filtered_cols]


class DummyDataGenerator:
    """Main interactive CLI"""
    
    def __init__(self):
        self.db_type = None
        self.connector = None
        self.schema = None
        self.table = None
    
    def select_db_type(self) -> str:
        """Step 1: Select database type"""
        print("\n" + "="*60)
        print("DUMMY DATA GENERATOR - Multi-Database Support")
        print("="*60)
        print("\nSelect Database Type:")
        print("1. MySQL")
        print("2. PostgreSQL")
        print("3. Oracle")
        
        while True:
            choice = input("\nEnter choice (1-3): ").strip()
            if choice == '1':
                return 'mysql'
            elif choice == '2':
                return 'postgresql'
            elif choice == '3':
                return 'oracle'
            else:
                print("✗ Invalid choice. Try again.")
    
    def input_connection_string(self, db_type: str) -> Dict[str, Any]:
        """Step 2: Input connection parameters"""
        print("\n" + "-"*60)
        print("Connection Parameters")
        print("-"*60)
        
        params = {}
        
        if db_type == 'mysql':
            params['host'] = input("Host (default: localhost): ").strip() or 'localhost'
            params['port'] = int(input("Port (default: 3306): ").strip() or 3306)
            params['user'] = input("User: ").strip()
            params['password'] = input("Password: ").strip()
            params['database'] = input("Database: ").strip()
        
        elif db_type == 'postgresql':
            params['host'] = input("Host (default: localhost): ").strip() or 'localhost'
            params['port'] = int(input("Port (default: 5432): ").strip() or 5432)
            params['user'] = input("User: ").strip()
            params['password'] = input("Password: ").strip()
            params['database'] = input("Database: ").strip()
        
        elif db_type == 'oracle':
            params['host'] = input("Host: ").strip()
            params['port'] = int(input("Port (default: 1521): ").strip() or 1521)
            params['user'] = input("User: ").strip()
            params['password'] = input("Password: ").strip()
            params['service_name'] = input("Service Name (e.g., xe): ").strip()
        
        return params
    
    def select_table(self) -> Tuple[str, str]:
        """Step 3 & 4: Select schema and table"""
        print("\n" + "-"*60)
        print("Schema & Table Selection")
        print("-"*60)
        
        schema = input("Schema name: ").strip()
        table = input("Table name: ").strip()
        
        return schema, table
    
    def inspect_table(self, schema: str, table: str) -> List[ColumnInfo]:
        """Step 5: Inspect table structure"""
        print("\n" + "-"*60)
        print(f"Inspecting {schema}.{table}")
        print("-"*60)
        
        columns = self.connector.get_columns(schema, table)
        
        if not columns:
            print(f"✗ Table {schema}.{table} not found or has no columns")
            return None
        
        print(f"\n✓ Found {len(columns)} columns:\n")
        print(f"{'Column Name':<25} {'Data Type':<20} {'Nullable':<10} {'PK':<5} {'FK':<5}")
        print("-" * 70)
        
        for col in columns:
            nullable = "YES" if col.nullable else "NO"
            pk = "YES" if col.is_pk else ""
            fk = f"→ {col.fk_table}.{col.fk_column}" if col.is_fk else ""
            print(f"{col.name:<25} {col.data_type:<20} {nullable:<10} {pk:<5} {fk:<5}")
        
        return columns
    
    def input_row_count(self) -> int:
        """Step 6: Input desired row count"""
        print("\n" + "-"*60)
        print("Generate Configuration")
        print("-"*60)
        
        while True:
            try:
                count = int(input("How many rows to generate? (1-100000): ").strip())
                if 1 <= count <= 100000:
                    return count
                else:
                    print("✗ Enter a number between 1 and 100000")
            except ValueError:
                print("✗ Invalid input. Enter a number.")
    
    def execute_injection(self, columns: List[ColumnInfo], count: int):
        """Step 7: Generate and inject data"""
        print("\n" + "-"*60)
        print("Data Generation & Injection")
        print("-"*60)
        
        generator = DataGenerator(self.connector)
        rows, col_names = generator.generate_rows(columns, count)
        
        print(f"\n✓ Generated {len(rows)} rows")
        print(f"✓ Columns to insert: {', '.join(col_names)}")
        
        confirm = input("\nProceed with injection? (yes/no): ").strip().lower()
        if confirm != 'yes':
            print("✗ Cancelled")
            return
        
        try:
            inserted = self.connector.batch_insert(self.schema, self.table, col_names, rows)
            print(f"\n✓ Successfully inserted {inserted} rows into {self.schema}.{self.table}")
            
            summary = {
                'database': self.db_type,
                'schema': self.schema,
                'table': self.table,
                'rows_inserted': inserted,
                'timestamp': datetime.now().isoformat()
            }
            print(f"\n{json.dumps(summary, indent=2)}")
        except Exception as e:
            print(f"✗ Injection failed: {e}")
    
    def run(self):
        """Main execution flow"""
        try:
            # Step 1: Select DB type
            self.db_type = self.select_db_type()
            
            # Step 2: Get connection params
            conn_params = self.input_connection_string(self.db_type)
            
            # Step 3: Create connector
            if self.db_type == 'mysql' and MYSQL_AVAILABLE:
                self.connector = MySQLConnector(conn_params)
            elif self.db_type == 'postgresql' and POSTGRES_AVAILABLE:
                self.connector = PostgreSQLConnector(conn_params)
            elif self.db_type == 'oracle' and ORACLE_AVAILABLE:
                self.connector = OracleConnector(conn_params)
            else:
                print(f"✗ {self.db_type} driver not installed")
                return
            
            # Step 4: Validate connection
            if not self.connector.connect():
                return
            
            # Step 5: Select schema and table
            self.schema, self.table = self.select_table()
            
            # Step 6: Inspect table
            columns = self.inspect_table(self.schema, self.table)
            if not columns:
                return
            
            # Step 7: Input row count
            row_count = self.input_row_count()
            
            # Step 8: Generate and inject
            self.execute_injection(columns, row_count)
        
        except KeyboardInterrupt:
            print("\n\n✗ Cancelled by user")
        except Exception as e:
            print(f"\n✗ Error: {e}")
        finally:
            if self.connector:
                self.connector.close()


if __name__ == '__main__':
    generator = DummyDataGenerator()
    generator.run()

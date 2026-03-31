"""
工业级数据库连接池与 ORM 封装 (Database Client)

核心特性：
1. 高可用连接池 (Connection Pooling)：基于 SQLAlchemy 引擎，支持池化复用与连接自动回收 (Pool Recycle)，防止 MySQL/PostgreSQL 经典的长连接 8 小时断开问题。
2. 上下文管理器 (Context Manager)：通过 @contextmanager 封装 session_scope，确保无论业务代码是否抛出异常，Session 都能被自动 commit 或 rollback，并完美释放回连接池。
3. 线程安全 (Thread Safety)：通过 sessionmaker 创建独立会话，保障多并发 Agent 同时读写工单数据时不发生脏读。
4. 抽象业务操作：直接为 Watcher Agent 提供拉取“待审计工单”和“保存审计结果”的强类型接口。

Copyright (c) 2026 ZhouWei & Team. All Rights Reserved.
"""

import os
from contextlib import contextmanager
from typing import List, Dict, Any, Generator
from loguru import logger
from datetime import datetime

from sqlalchemy import create_engine, Column, String, Text, Integer, Boolean, DateTime
from sqlalchemy.orm import sessionmaker, declarative_base, Session
from sqlalchemy.exc import SQLAlchemyError

# =============================================================================
# 1. ORM 基础模型定义 (Data Models)
# =============================================================================
Base = declarative_base()

class IncidentLog(Base):
    """工单流水表：记录所有突发事件的流转状态，供 Watcher 巡检"""
    __tablename__ = 'incident_logs'

    id = Column(Integer, primary_key=True, autoincrement=True)
    case_id = Column(String(50), unique=True, nullable=False, index=True)  # 案卷号，加索引加速查询
    severity = Column(String(10), nullable=False)  # P0, P1, P2...
    dispatched_instruction = Column(Text, nullable=False)  # 指挥官下发的指令
    employee_replies = Column(Text, nullable=True)  # 员工反馈流 (JSON String)
    created_at = Column(DateTime, default=datetime.utcnow)  # 事件发生时间
    is_resolved = Column(Boolean, default=False, index=True)  # 是否已闭环
    audit_status = Column(String(20), default="PENDING")  # PENDING, PASSED, VIOLATED


class SOPDocument(Base):
    """标准作业程序文档表：记录景区 SOP 操作规范，供 AI 指挥官查询执行"""
    __tablename__ = 'sop_documents'

    id = Column(Integer, primary_key=True, autoincrement=True)
    category = Column(String(50), nullable=False)  # 分类：安全/票务/设施/客流/投诉
    title = Column(String(200), nullable=False)   # 标题
    content = Column(Text, nullable=False)        # SOP 正文
    priority = Column(Integer, default=3)         # 优先级（1最高）
    version = Column(String(20), default="1.0")   # 版本号
    updated_at = Column(DateTime, default=datetime.utcnow)  # 更新时间


# =============================================================================
# 2. 核心引擎与连接池配置 (Engine & Pool)
# =============================================================================
class DatabaseManager:
    """数据库全局管理器 (单例模式)"""

    def __init__(self):
        # 生产环境优先从环境变量读取 DB URI (例如 postgresql://user:pass@host/dbname)
        # 默认降级为本地 SQLite，方便开发测试
        self.db_uri = os.environ.get("DATABASE_URI", "sqlite:///../../data/memory.db")
        
        # 针对 SQLite 和关系型数据库做不同的连接池配置
        connect_args = {}
        if self.db_uri.startswith("sqlite"):
            # SQLite 不支持高并发的传统连接池，必须关闭 check_same_thread
            connect_args = {"check_same_thread": False}
            self.engine = create_engine(self.db_uri, connect_args=connect_args)
            logger.info(f"数据库引擎初始化完成: SQLite 本地模式 ({self.db_uri})")
        else:
            # 针对 MySQL/PG 的工业级连接池配置
            self.engine = create_engine(
                self.db_uri,
                pool_size=20,               # 常驻连接池大小
                max_overflow=10,            # 突发并发时允许溢出的最大连接数
                pool_pre_ping=True,         # 每次从池中拿连接前先 ping 一下，防止拿到死连接 (极其重要！)
                pool_recycle=3600,          # 连接存活 1 小时后强制回收，防 8 小时断开 Bug
                connect_args=connect_args
            )
            logger.info(f"数据库引擎初始化完成: 生产级关系型数据库连接池机制已激活。")

        # 创建 Session 工厂
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        
        # 自动创建所有表 (工业级项目中通常使用 Alembic 进行迁移，这里为系统冷启动提供兜底)
        Base.metadata.create_all(bind=self.engine)

    @contextmanager
    def session_scope(self) -> Generator[Session, None, None]:
        """
        提供事务范围的会话上下文管理器。
        业务层只需要: with db.session_scope() as session:
        无需关心 commit, rollback 和 close。
        """
        session = self.SessionLocal()
        try:
            yield session
            session.commit()
        except SQLAlchemyError as e:
            session.rollback()
            logger.error(f"[DB_ERROR] 数据库事务执行失败，已自动回滚: {e}")
            raise
        finally:
            session.close() # 释放连接回池中

# 初始化全局数据库连接池单例
db_manager = DatabaseManager()


# =============================================================================
# 3. 业务数据访问层 (Data Access Object - DAO)
# =============================================================================

class WatcherDAO:
    """专为 Watcher(鹰眼) Agent 提供的数据访问对象"""

    @staticmethod
    def fetch_pending_audits(limit: int = 20) -> List[Dict[str, Any]]:
        """捞取一批待审计的、且尚未闭环的工单日志"""
        with db_manager.session_scope() as session:
            # 查询所有尚未闭环，且审计状态为 PENDING 的工单
            records = session.query(IncidentLog).filter(
                IncidentLog.is_resolved == False,
                IncidentLog.audit_status == "PENDING"
            ).order_by(IncidentLog.created_at.asc()).limit(limit).all()

            # 转换为 Python Dict 供大模型消费
            results = []
            now = datetime.utcnow()
            for r in records:
                elapsed = int((now - r.created_at).total_seconds() / 60)
                results.append({
                    "case_id": r.case_id,
                    "severity": r.severity,
                    "dispatched_instruction": r.dispatched_instruction,
                    "employee_replies": r.employee_replies,
                    "elapsed_minutes": elapsed,  # 动态计算耗时，极其关键
                    "is_resolved": r.is_resolved
                })
            
            logger.debug(f"[DAO] 成功捞取 {len(results)} 条待审计工单记录。")
            return results

    @staticmethod
    def mark_audit_completed(case_id: str, is_violation: bool) -> None:
        """更新工单的审计状态"""
        with db_manager.session_scope() as session:
            record = session.query(IncidentLog).filter(IncidentLog.case_id == case_id).first()
            if record:
                record.audit_status = "VIOLATED" if is_violation else "PASSED"
                logger.debug(f"[DAO] 案卷 {case_id} 审计状态已更新为 {record.audit_status}")
            else:
                logger.warning(f"[DAO] 试图更新不存在的案卷 {case_id}")
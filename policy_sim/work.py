"""Lawful business overview and full documents in the native actor workspace."""
from copy import deepcopy
import json
import hashlib
import os
from pathlib import Path
import tempfile

BUSINESS_FIELDS = frozenset({"actor_id", "role", "round", "last_receipt", "visible_tickets",
    "projects", "topics", "inbox", "sent_messages", "materials", "public_rules", "resources", "candidate_options"})
# Strip metadata at its owning wrapper, never by recursively deleting similarly
# named fields from business documents or candidate parameters.
MATERIAL_FIELDS = frozenset({"as_of_round", "source_index", "raw", "delivered_raw_ids",
    "analyses", "read_limit", "reads_used", "window_start", "note"})
SOURCE_FIELDS = frozenset({"source_id", "kind", "object", "created_round", "recipient", "received_round", "data"})


def business_source(source):
    return {key: deepcopy(value) for key, value in source.items() if key in SOURCE_FIELDS}


def business_materials(materials):
    result = {key: deepcopy(value) for key, value in materials.items() if key in MATERIAL_FIELDS}
    for key in ("source_index", "raw"):
        if key in result:
            result[key] = [business_source(source) for source in result[key]]
    if "analyses" in result:
        result["analyses"] = [{"kind": "诉求分办分析" if packet["service"] == "A" else "关联诉求分析",
            "target": packet["target"] if packet["service"] == "A" else "已取得的相关诉求",
            "payload": deepcopy(packet["payload"])} for packet in materials["analyses"]]
    # Omit only index metadata already present verbatim in a full raw row.
    raw = {row["source_id"]: row for row in result.get("raw", [])}
    result["source_index"] = [row for row in result.get("source_index", [])
        if not (row.get("source_id") in raw and
                all(key in raw[row["source_id"]] and raw[row["source_id"]][key] == value
                    for key, value in row.items()))]
    result["source_catalog_note"] = "可查询来源包括 source_index 与 raw 中的全部 source_id；raw 已列全文，目录不重复列出。"
    if result.get("read_limit") is None:
        result.pop("read_limit", None)
        result.pop("reads_used", None)
    return result


def business_receipt(receipt):
    return {key: deepcopy(value) for key, value in receipt.items()
            if key in {"actor_id", "round", "status", "code", "action_kind", "target", "detail"}}


def business_material_result(result):
    return {key: ([business_source(row) for row in value] if key == "sources" else deepcopy(value))
            for key, value in result.items() if key in {"actor_id", "round", "reason", "sources"}}


def lawful_work(observation):
    result = {key: deepcopy(value) for key, value in observation.items() if key in BUSINESS_FIELDS}
    if "materials" in result:
        result["materials"] = business_materials(result["materials"])
    for field in ("inbox", "sent_messages"):
        # An empty status reply is an honest complete answer, not a truncation;
        # say so in-band or recipients re-read it waiting for content.
        for message in result.get(field, []):
            payload = message.get("payload")
            if isinstance(payload, dict) and payload.get("records") == []:
                message["content_note"] = "本消息未附任何记录：发送方按规则无可送达内容，空records即完整答复，重读不会产生新信息。"
    for project in result.get("projects", []):
        evidence = project.get("evidence")
        if evidence and any(record.get("kind") == "project_diagnosis" and
                            record.get("data", {}).get("evidence") == evidence
                            for record in project.get("received_records", [])):
            project.pop("evidence")
            project["evidence_note"] = "现场调查正文见本项目 received_records 中 project_diagnosis 的 data.evidence。"
    return result


WORK_BYTES = 12000
DOCUMENT_BYTES = 6000
MAX_MATERIAL_BATCH = 4
REQUEST_BYTES = 240000  # margin below the unchanged 262144-byte transport ceiling
SECTION_BYTES = 16000
PACE_FROM_CALL = 5
WORK_SECTIONS = ("candidate_options", "visible_tickets", "projects", "topics", "inbox",
                 "sent_messages", "public_rules", "source_catalog", "analyses", "last_receipt", "resources")

READ_STUB_NOTE = ("本页与本轮先前读取完全相同，内容已在你此前的工具观察中；重读不会产生新信息。"
                  "可读取其它章节或材料，或直接提交候选。")
MATERIAL_STUB_NOTE = ("这些来源本轮已读取，正文已在你此前的工具观察中；重读不会产生新信息。"
                      "可读取其它来源，或直接提交候选。")




def source_catalog(observation):
    materials = business_materials(observation.get("materials", {}))
    by_id = {}
    for source in [*materials.get("source_index", []), *materials.get("raw", [])]:
        by_id[source["source_id"]] = {k: deepcopy(source[k]) for k in
            ("source_id", "kind", "object", "created_round", "received_round") if k in source}
    return list(by_id.values())


def business_observation(observation):
    """One legal overview usable by both actors and environment routers."""
    full = lawful_work(observation)
    full["analyses"] = full.pop("materials", {}).get("analyses", [])
    full["source_catalog"] = source_catalog(observation)
    current = {
        "turn_contract": "从当前candidate_options选择一个候选，通过ask_env提交：instruction='submit candidate {candidate_id} with reason {reason}'，variables={candidate_id,reason}；propose_project候选必须在variables中另附analysis={source_ids,hypothesis}。收到queued回执后finish。wait也必须由本人明确提交。",
        "query_help": "read_work用instruction='read_work section {section} offset {offset}'；read_materials用instruction='read_materials source_ids {source_ids} reason {reason}'，source_ids是单个source_id字符串或其列表（每次最多4个、不可重复），只接受source_catalog中的source_id并返回全文。已知候选可直接submit，无需再次检查或替主体重新决策。空集合为完整空结果。"}
    budgets = {"candidate_options": 6000, "projects": 1200, "visible_tickets": 3500,
               "source_catalog": 2200, "inbox": 500, "sent_messages": 300}
    # Keep choices first. Remaining sections retain an executable query when
    # their actual content does not fit; never emit actor-only file paths.
    order = ("actor_id", "role", "round", "last_receipt", "resources",
             *(key for key in WORK_SECTIONS if key not in {"last_receipt", "resources"}))
    for key in order:
        original = full.get(key, [])
        value = original
        if key in {"inbox", "sent_messages"}:
            value = {"count": len(value), "complete": not value,
                "recent": [{k: deepcopy(row[k]) for k in
                    ("id", "sender", "recipient", "kind", "object", "round", "delivered_round", "content_note") if k in row}
                    for row in value[-3:]]}
        location = {"read_work": {"section": key, "offset": 0}}
        if _size(value) <= budgets.get(key, 350) and _size({**current, key: value}) <= WORK_BYTES - 1200:
            current[key] = deepcopy(value)
            if key in {"inbox", "sent_messages"} and original:
                current[key].update(location)
        else:
            current[key] = {**location,
                "count": len(original) if isinstance(original, (list, dict)) else 1,
                "complete": False}
    if _size(current) > WORK_BYTES:
        raise ValueError("Lawful current work exceeds its size contract")
    return current


def read_stub(section, offset, count):
    return {"section": section, "offset": offset, "unchanged_since_last_read": True,
            "read_count_this_turn": count, "note": READ_STUB_NOTE}


def material_stub(source_ids, count):
    return {"source_ids": list(source_ids), "unchanged_since_last_read": True,
            "read_count_this_turn": count, "note": MATERIAL_STUB_NOTE}


def pace_note(call_index):
    """In-band pacing fact once the actor's own loop is more than half spent.

    States only the actor's own iteration facts; whether to submit, wait or
    keep reading remains the actor's decision.
    """
    if type(call_index) is int and call_index >= PACE_FROM_CALL:
        return (f"这是本主体本轮第{call_index + 1}次工具调用（官方循环上限10次）；"
                "排队回执之后还需要单独一次finish，信息足够时请尽快提交候选。")
    return None


def paced(call_index, result):
    note = pace_note(call_index)
    if note is not None and isinstance(result, dict):
        result = {**result, "pace_note": note}
    return result

BUSINESS_CONTRACT = {
    "reason": "reason仅记录本人的行动依据，不是发给其他岗位的自由文本消息；个人记忆中的意图也不是办理前置条件。",
    "status": "query_status请求既有办理记录，report_status/reply_status送达既有记录；不能用reason索取或发送新增论证。",
    "review": "review_project提交approve/revise/reject专业意见；意见完成时经官方邮箱作为带记录的回执送达项目负责人，接收方收到任务与意见，reason不在送达正文中。",
    "plan": "draft_plan使用既定replace_shared_main方案；重复拟案更新版本并取消旧任务，不修改工程内容。当前无自由编辑方案或重复现场诊断操作。",
    "choice": "以已收到的证据、当前候选和真实结算回执作判断；可选择评审、办理、合法撤项或wait，不以个人期待新增不存在的前置条件。",
}


def _size(value):
    # Measure the indented JSON actually placed inside the official user prompt.
    return len(json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8"))


def read_work_section(observation, section, offset=0):
    """Read complete business records, with a bounded record-based continuation."""
    if section not in WORK_SECTIONS or type(offset) is not int or offset < 0:
        raise ValueError("Unknown legal work section or invalid offset")
    if section == "source_catalog":
        value = source_catalog(observation)
    elif section == "analyses":
        value = business_materials(observation.get("materials", {})).get("analyses", [])
    else:
        value = lawful_work(observation).get(section)
    if value is None:
        if offset:
            raise ValueError("Offset is outside this legal section")
        return {"section": section, "offset": 0, "total": 0, "as_of_round": observation.get("round"),
                "value": None, "next_offset": None, "complete": True}
    is_dict = isinstance(value, dict)
    records = list(value.items()) if is_dict else list(value)
    if offset > len(records):
        raise ValueError("Offset is outside this legal section")
    def page(selected):
        end = offset + len(selected)
        return {"section": section, "offset": offset, "total": len(records),
            "as_of_round": observation.get("round"),
            "value": dict(selected) if is_dict else selected,
            "next_offset": end if end < len(records) else None, "complete": end == len(records)}
    selected = []
    for record in records[offset:]:
        if _size(page(selected + [record])) > SECTION_BYTES:
            if not selected:
                raise ValueError("This record is too large; request its individual source_id through read_materials")
            break
        selected.append(deepcopy(record))
    return page(selected)


class WorkContext:
    """Sole owner of the current observation and its legal material deliveries."""
    def __init__(self, observation):
        self.observation = deepcopy(observation)
        self.default_raw = deepcopy(observation["materials"]["raw"])
        # Turn-scoped read ledger: an identical re-read within the same round
        # has no new information, so its content is not re-served (cache-HIT
        # semantics). The ledger never crosses a round boundary.
        self.read_pages = {}
        self.read_counts = {}
        self.read_sources = {}

    @property
    def current_work(self):
        return business_observation(self.observation)

    def read_work_once(self, section, offset):
        page = read_work_section(self.observation, section, offset)
        key = ("work", section, offset)
        if self.read_pages.get(key) == page:
            self.read_counts[key] = self.read_counts.get(key, 1) + 1
            return read_stub(section, offset, self.read_counts[key])
        self.read_pages[key] = page
        self.read_counts[key] = 1
        return page

    def seen_materials(self, ids):
        key = tuple(sorted(ids))
        return key in self.read_sources

    def mark_materials(self, ids):
        self.read_sources[tuple(sorted(ids))] = True

    def material_repeat_count(self, ids):
        key = tuple(sorted(ids))
        self.read_counts[("materials", key)] = self.read_counts.get(("materials", key), 1) + 1
        return self.read_counts[("materials", key)]

    def receive(self, result):
        from .materials import apply_read
        self.observation = apply_read(self.observation, result)



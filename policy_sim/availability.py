"""Single owner of task-action availability across the environment's seams.

Candidate generation (PolicyWorld.observe), execution gating
(PolicyWorld._task_action) and rejection detail all ask this module the same
question: which prerequisites of this pending knowledge task has the actor
not received a completed handoff for. The answer is computed strictly from
the actor's lawful knowledge, never from the world's hidden state, so it can
be shown in-band without a delivery. The executor additionally applies world
physics at settlement; generation-time annotations are advisory and may
legitimately differ by the settlement boundary.
"""

REMEDY_NOTE = ("前置作业的完成交接尚未送达本岗位；可用query_status向相关负责人核实，"
               "或由事项负责人发起协同并等待任务送达。")


def task_blockers(world, actor, view):
    """Return the actor-viewpoint blockers for one pending task; [] when executable.

    A prerequisite blocks when the actor's own knowledge holds no completed
    handoff for it — exactly the receipt half the executor checks — so the
    annotation and the rejection detail can never disagree.
    """
    blockers = []
    for pid in view.get('prerequisites', []):
        received = world.knowledge[str(actor)]['tasks'].get(pid)
        if received is None or received.get('state') != 'completed':
            blockers.append({'task': pid, 'received_completion': False, 'note': REMEDY_NOTE})
    return blockers

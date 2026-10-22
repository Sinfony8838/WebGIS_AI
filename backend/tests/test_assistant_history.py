import pytest
from backend.app.store import RuntimeStore
from backend.app.services.assistant_profiles import bind_conversation
from backend.tests import test_auth_api as auth_tests

@pytest.fixture
def store(tmp_path):
    instance=RuntimeStore(tmp_path / "runtime.json")
    yield instance
    instance.close()

def test_folder_pin_move_delete_restore_and_persistence(store):
    pid=store.create_project("demo").project_id
    c=bind_conversation(store,pid,"chat","","alice")
    store.append_conversation_message(c.conversation_id,"user","Original content")
    folder=store.create_assistant_folder(pid,"alice","My topic")
    store.update_assistant_conversation(c.conversation_id,"alice",{"folder_id":folder.folder_id,"pinned":True})
    store.update_assistant_folder(pid,"alice",folder.folder_id,{"pinned":True})
    store.update_assistant_conversation(c.conversation_id,"alice",{"deleted":True})
    assert store.list_assistant_conversations(pid,"alice","chat")==[]
    assert len(store.list_assistant_conversations(pid,"alice","chat",True))==1
    with pytest.raises(KeyError):bind_conversation(store,pid,"chat",c.conversation_id,"alice")
    saved=RuntimeStore(store.state_file,read_only=True)
    try:
        assert saved.assistant_folders[folder.folder_id].pinned
        assert saved.conversations[c.conversation_id].deleted_at
    finally:saved.close()
    store.update_assistant_conversation(c.conversation_id,"alice",{"deleted":False})
    row=store.list_assistant_conversations(pid,"alice","chat")[0]
    assert row["pinned"] and row["folder_id"]==folder.folder_id
    assert row["title"]=="Original content"
    store.update_assistant_folder(pid,"alice",folder.folder_id,{},delete=True)
    assert store.list_assistant_conversations(pid,"alice","chat")[0]["folder_id"]==""
    assert store.get_conversation(c.conversation_id).raw_messages

def test_history_scope_and_busy_delete(store):
    p=store.create_project("one").project_id
    q=store.create_project("two").project_id
    c=bind_conversation(store,p,"operate","","alice")
    own=store.create_assistant_folder(p,"alice","own")
    other=store.create_assistant_folder(p,"bob","other")
    cross=store.create_assistant_folder(q,"alice","cross")
    for folder in (other,cross):
        with pytest.raises(ValueError):store.update_assistant_conversation(c.conversation_id,"alice",{"folder_id":folder.folder_id})
        with pytest.raises(KeyError):store.update_assistant_folder(p,"alice",folder.folder_id,{"pinned":True})
    with pytest.raises(KeyError):store.update_assistant_conversation(c.conversation_id,"bob",{"deleted":True})
    assert [r["folder_id"] for r in store.list_assistant_folders(p,"alice")]==[own.folder_id]
    assert store.list_assistant_conversations(p,"alice","chat")==[]
    job=store.create_job(project_id=p,job_type="assistant",title="busy",request={"conversation_id":c.conversation_id})
    with pytest.raises(ValueError):store.update_assistant_conversation(c.conversation_id,"alice",{"deleted":True})
    store.set_job_status(job.job_id,"completed")
    store.update_assistant_conversation(c.conversation_id,"alice",{"deleted":True})
    assert c.deleted_at

def test_history_endpoints_scope_and_soft_delete():
    env=auth_tests.AuthApiTest()
    env.setUp()
    try:
        user,csrf=env.bootstrap_admin()
        client=env.client
        headers={"X-WebGIS-CSRF":csrf}
        store=auth_tests.app_main.runtime.store
        pid=store.create_project("history",owner_user_id=user["user_id"]).project_id
        c=bind_conversation(store,pid,"chat","",user["user_id"])
        folder=client.post(f"/projects/{pid}/assistant/folders",json={"name":"Topic"},headers=headers)
        assert folder.status_code==200,folder.text
        fid=folder.json()["folder_id"]
        url=f"/assistant/conversations/{c.conversation_id}"
        assert client.patch(url,json={"pinned":True,"folder_id":fid},headers=headers).status_code==200
        listing=client.get(f"/projects/{pid}/assistant/conversations?mode=chat").json()
        assert listing["items"][0]["folder_id"]==fid and listing["items"][0]["pinned"]
        assert client.patch(url,json={"deleted":True},headers=headers).status_code==200
        assert client.get(url).status_code==404
        assert len(client.get(f"/projects/{pid}/assistant/conversations?mode=chat&deleted=true").json()["items"])==1
        assert client.patch(url,json={"deleted":False},headers=headers).status_code==200
        assert client.get(url).status_code==200
        foreign=bind_conversation(store,pid,"chat","","other")
        assert client.patch(f"/assistant/conversations/{foreign.conversation_id}",json={"deleted":True},headers=headers).status_code==403
    finally:
        env.tearDown()
        env.doCleanups()


def test_legacy_clarification_is_not_duplicated_in_restored_history(store):
    from backend.app.runtime import WebGISRuntime
    pid=store.create_project("legacy").project_id
    c=bind_conversation(store,pid,"operate","","alice")
    job=store.create_job(project_id=pid,job_type="assistant",title="clarify",request={"conversation_id":c.conversation_id,"actor_user_id":"alice"})
    store.append_conversation_message(c.conversation_id,"assistant","Which layer?")
    store.set_job_status(job.job_id,"completed",result={"assistant_message":"Which layer?"})
    runtime=object.__new__(WebGISRuntime)
    runtime.store=store
    messages=runtime.get_conversation(c.conversation_id)["messages"]
    assert len(messages)==1
    assert messages[0]["execution"]["job_id"]==job.job_id

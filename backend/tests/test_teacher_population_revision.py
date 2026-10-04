import copy
import json
import sqlite3
import unittest
import zlib
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest
from backend.app.services.population_zonal import PopulationCountPackage, PopulationDataError
from backend.app.services.resource_access import is_shared_public_asset, resolve_public_reference, TEACHER_REVISION_SHA


def test_registered_teacher_figures_are_shared_but_neighbors_and_wrong_sources_are_not(tmp_path):
    from types import SimpleNamespace
    config=SimpleNamespace(uploads_dir=tmp_path/'uploads',outputs_dir=tmp_path/'outputs')
    folder=config.uploads_dir/'teacher_population_revised';folder.mkdir(parents=True)
    figure=folder/'source_row_21_2.png';figure.write_bytes(b'png')
    neighbor=folder/'source_row_21_99.png';neighbor.write_bytes(b'private')
    manifest={'source_sha256':TEACHER_REVISION_SHA,'items':[{'filename':figure.name}]}
    (folder/'manifest.json').write_text(json.dumps(manifest))
    assert is_shared_public_asset(config,resolve_public_reference(config,'/files/uploads/teacher_population_revised/'+figure.name))
    assert not is_shared_public_asset(config,neighbor)
    assert not is_shared_public_asset(config,folder/'manifest.json')
    manifest['source_sha256']='wrong-source';(folder/'manifest.json').write_text(json.dumps(manifest))
    assert not is_shared_public_asset(config,figure)


@pytest.fixture
def counts(tmp_path):
    values=np.arange(1,10,dtype='<f4').reshape(3,3)
    values[0,0]=np.nan
    (tmp_path/'package.json').write_text(json.dumps({'format':'worldpop-count-tiles-v1','units':'persons_per_pixel',
        'total_population':44,'bbox':[0,0,3,3],'resolution_degrees':[1,1],'tile_size':3,'year':2015,'source':{'name':'fixture'}}))
    with sqlite3.connect(tmp_path/'counts.sqlite') as db:
        db.execute('CREATE TABLE tiles(row,col,height,width,data)')
        db.execute('INSERT INTO tiles VALUES(0,0,3,3,?)',(zlib.compress(values.tobytes()),))
    return PopulationCountPackage(tmp_path)


def polygon(x0,y0,x1,y1):
    return {'type':'Polygon','coordinates':[[[x0,y0],[x1,y0],[x1,y1],[x0,y1],[x0,y0]]]}


def test_count_conservation_and_no_area_scaling(counts):
    result=counts.summarize(polygon(0,0,2,3))
    assert result['inside_population']==26
    assert result['outside_population']==18
    assert result['inside_population']+result['outside_population']==result['total_population']
    assert result['inside_percent']+result['outside_percent']==100
    assert counts.summarize(polygon(0,0,3,3))['inside_population']==44


def test_holes_disjoint_polygons_and_missing_are_distinct(counts):
    area=polygon(0,0,3,3);area['coordinates'].append(polygon(1,1,2,2)['coordinates'][0])
    assert counts.summarize(area)['inside_population']==39
    multi={'type':'MultiPolygon','coordinates':[polygon(0,0,1,1)['coordinates'],polygon(2,2,3,3)['coordinates']]}
    assert counts.summarize(multi)['inside_population']==10
    assert counts.summarize(polygon(0,2,1,3))['inside_population'] is None
    assert counts.summarize(polygon(9,9,10,10))['status']=='no_data'


@pytest.mark.parametrize('geometry',[{'type':'LineString','coordinates':[[0,0],[1,1]]},
    {'type':'Polygon','coordinates':[[[0,0],[2,2],[2,0],[0,2],[0,0]]]},polygon(-181,0,-170,3)])
def test_invalid_geometry_rejected(counts,geometry):
    with pytest.raises(PopulationDataError):counts.summarize(geometry)


class TeacherRevisionTest(unittest.TestCase):
    def build_runtime(self):
        from tests.test_lessons import LessonServiceTest
        return LessonServiceTest.build_runtime(self)

    def test_complete_sequence_unlimited_pacing_and_question_sources(self):
        runtime,store,_=self.build_runtime();lesson=store.get_lesson('lesson_builtin_population_teacher_revised')
        self.assertEqual(len(lesson.stages),12)
        self.assertEqual(sum(len(s['actions']) for s in lesson.stages),41)
        self.assertEqual(lesson.metadata['pacing_mode'],'teacher')
        self.assertTrue(all(s['minutes']==0 and s['timing_mode']=='teacher' for s in lesson.stages))
        self.assertEqual([s['stage_id'] for s in lesson.stages][:5],['world_intro','world_features','reading_method','china_practice','shanghai_practice'])
        self.assertTrue(lesson.find_stage('china_practice')['scene']['layer_visibility']['generated_hu_line'])
        self.assertEqual(len(lesson.find_stage('reinforcement')['questions']),5)
        self.assertTrue(all(q['answer'] and q['explanation'] for s in lesson.stages for q in s['questions']))

    def test_action_uses_frozen_snapshot_and_does_not_reenter_stage(self):
        from backend.app.services.teacher_lesson_actions import apply_action
        runtime,store,pid=self.build_runtime();lid='lesson_builtin_population_teacher_revised'
        sid=runtime.classroom.create_class_session(lid,pid)['session']['session_id']
        runtime.classroom.enter_session_stage(sid,'human_factors')
        before=copy.deepcopy(store.get_class_session(sid).to_dict())
        modified=copy.deepcopy(store.get_lesson(lid).stages)
        modified[7]['actions'][0]['note']='later edit'
        runtime.classroom.lesson_service.update_lesson(lid,{'stages':modified})
        result=apply_action(runtime,sid,'human_factors','production')
        self.assertNotEqual(result['action']['note'],'later edit')
        self.assertEqual(len([e for e in before['events'] if e['type']=='stage_enter']),len([e for e in result['session']['events'] if e['type']=='stage_enter']))
        self.assertEqual(result['session']['responses'],{})
        with self.assertRaises(ValueError):apply_action(runtime,sid,'world_intro','migration_video')

    def test_rehearsal_keeps_teacher_pacing_and_validates_complete_plan(self):
        runtime,store,pid=self.build_runtime();source=store.get_lesson('lesson_builtin_population_teacher_revised')
        teacher=runtime.classroom.lesson_service.create_lesson(source.to_dict())
        record=runtime.classroom.create_lesson_rehearsal(pid,teacher.lesson_id)['rehearsal']
        self.assertEqual(record['working_copy']['duration_minutes'],0)
        self.assertEqual(record['working_copy']['pacing_mode'],'teacher')
        report=runtime.classroom.lesson_rehearsal_report(record['rehearsal_id'])['report']
        self.assertEqual(report['errors'],[])
        self.assertTrue(report['ready'])

    def test_missing_teaching_resource_prevents_scene_mutation(self):
        runtime,store,pid=self.build_runtime();before=store.get_project(pid).to_dict()
        with patch.object(runtime.teaching_map_service,'get_map',return_value={'available':False}):
            with self.assertRaises(ValueError):runtime.classroom.apply_lesson_scene(pid,'lesson_builtin_population_teacher_revised','world_intro')
        self.assertEqual(store.get_project(pid).to_dict(),before)

    def test_workflow_result_requires_current_class_action_and_renders_above_basemap(self):
        from backend.app.models import WorkflowRecord, LayerRecord
        from backend.app.services.teacher_lesson_actions import apply_workflow_result
        runtime,store,pid=self.build_runtime()
        # This unit test verifies workflow ownership and display order, not
        # private textbook deployment. Supply its image in the temporary data
        # directory so clean CI cannot accidentally depend on local assets.
        from PIL import Image
        map_info=runtime.teaching_map_service.get_map('finland_population')
        image=runtime.config.uploads_dir/'teaching_maps'/map_info['filename']
        Image.new('RGBA',(1,1),(0,0,0,0)).save(image)
        sid=runtime.classroom.create_class_session('lesson_builtin_population_teacher_revised',pid)['session']['session_id']
        runtime.classroom.enter_session_stage(sid,'finland_application')
        workflow=WorkflowRecord.create(pid);workflow.status='success';store.create_workflow(workflow)
        with self.assertRaises(ValueError):apply_workflow_result(runtime,sid,'finland_application',workflow.workflow_id)
        store.append_session_event(sid,'lesson_action',stage_id='finland_application',payload={'action_id':'finland_reproduce','workflow_id':workflow.workflow_id})
        path=runtime.config.outputs_dir/'finland-test.geojson'
        path.write_text(json.dumps({'type':'FeatureCollection','features':[{'type':'Feature','geometry':{'type':'Point','coordinates':[25,61]},'properties':{'density':10}}]}))
        store.register_artifact(pid,'','workflow_output','test',str(path),{'workflow_id':workflow.workflow_id,'kind':'geojson','relative_path':'finland-test.geojson'})
        raw=LayerRecord.create(name='raw',kind='vector',source='one_map_catalog',geometry_type='Point');raw.layer_id='one_map_finland_population_density_2015';store.upsert_layer(pid,raw)
        apply_workflow_result(runtime,sid,'finland_application',workflow.workflow_id)
        visible=[l for l in store.get_project(pid).layers if l.visible and l.metadata.get('teacher_topic')]
        self.assertEqual(len(visible),1);self.assertEqual(visible[0].z_index,30)
        self.assertEqual(len(visible[0].data['features']),1);self.assertFalse(raw.visible)
        runtime.classroom.enter_session_stage(sid,'reinforcement')
        self.assertFalse(visible[0].visible)
        with self.assertRaises(ValueError):apply_workflow_result(runtime,sid,'finland_application',workflow.workflow_id)

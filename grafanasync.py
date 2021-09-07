#!/usr/bin/python3

import os
import argparse
import requests
import secrets
import json
from collections import namedtuple

mluviidomain = os.getenv('MLUVII_DOMAIN', default='app.mluvii.com')
mluviiclientid = os.getenv('MLUVII_CLIENT_ID')
mluviiclientsecret = os.getenv('MLUVII_CLIENT_SECRET')

mluviiapiurl = f'https://{mluviidomain}/api/v1'

grafanaurl = os.getenv('GRAFANA_URL')
grafanaadmin = os.getenv('GRAFANA_USER')
grafanapass = os.getenv('GRAFANA_PASS')

grafanaapiurl = f'{grafanaurl}/api'
grafanaauth = requests.auth.HTTPBasicAuth(grafanaadmin, grafanapass)

homedashboardfile = os.getenv('HOME_DASHBOARD_FILE')

Company = namedtuple('Company',['name','company_id','org_id'])
User = namedtuple('User',['user_name','email','first_name','last_name','company_id','is_admin'])

def parse_arguments():
    parser = argparse.ArgumentParser()
    parser.add_argument('--companies', type=int, nargs='*')
    args = parser.parse_args()
    return args.companies

def get_mluvii_token():
    data = {
        'response_type': 'token',
        'grant_type': 'client_credentials',
        'client_id': mluviiclientid,
        'client_secret': mluviiclientsecret
    }
    resp = requests.post(f'https://{mluviidomain}/login/connect/token', data=data, headers={'Content-Type': 'application/x-www-form-urlencoded'})
    resp.raise_for_status()
    return resp.json()['access_token']

mluviiauth = {'Authorization': f'Bearer {get_mluvii_token()}'}

def sync_orgs(companyids):
    existing = get_existing_orgs()
    companies = get_mluvii_companies(companyids)
    orgs = {}
    for name, company_id in companies.items():
        if name in existing:
            orgs[company_id] = Company(name, company_id, existing[name])
        else:
            orgs[company_id] = Company(name, company_id, create_org(name))
    return orgs

def get_existing_orgs():
    resp = requests.get(f'{grafanaapiurl}/orgs?perpage=1000', auth=grafanaauth)
    resp.raise_for_status()
    ids = {}
    for it in resp.json():
        ids[it['name']] = it['id']
    return ids

def get_mluvii_companies(companyids):
    ids = {}
    if companyids is None:
        name, id = get_mluvii_company(None)
        ids[name] = id
        return ids
    for id in companyids:
        name, _ = get_mluvii_company(id)
        ids[name] = id
    return ids

def get_mluvii_company(id):
    suff = f'/{id}' if id is not None else ''
    resp = requests.get(f'{mluviiapiurl}/Companies{suff}', headers=mluviiauth)
    resp.raise_for_status()
    return resp.json()['name'], resp.json()['id']

def create_org(name):
    print(f'Organization {name}')
    resp = requests.post(f'{grafanaapiurl}/orgs', auth=grafanaauth, data={'name':name})
    resp.raise_for_status()
    return resp.json()['orgId']

def get_mluvii_users(org):
    resp = requests.get(f'{mluviiapiurl}/Users?companyId={org.company_id}', headers=mluviiauth)
    resp.raise_for_status()
    users = {}
    for u in resp.json():
        users[u['username']] = User(u['username'], u['email'], u['firstName'], u['lastName'], org.company_id, 'Admin' in u['globalRoles'])
    return users

def sync_org(org, users):
    create_users(org, users)
    switch_org(org)
    tokenauth = create_token_auth_header(org)
    sync_datasource(org, tokenauth)
    sync_home_dashboard(org, tokenauth)

def create_users(org, users):
    existing_users = get_org_users(org)
    for _, u in users.items():
        if (u.company_id == org.company_id) and (not u.user_name in existing_users):
            create_user(u, org)

def get_org_users(org):
    resp = requests.get(f'{grafanaapiurl}/orgs/{org.org_id}/users', auth=grafanaauth)
    resp.raise_for_status()
    logins = {}
    for it in resp.json():
        logins[it['login']] = it
    return logins

def add_user_to_org(user_name, org, role):
    data = {'loginOrEmail': user_name, 'role': role}
    resp = requests.post(f'{grafanaapiurl}/orgs/{org.org_id}/users', auth=grafanaauth, json=data)
    print(f'User {user_name} added to org {org.org_id} with role {role}')
    resp.raise_for_status()

def remove_user_from_org(user_name, user_id, org):
    resp = requests.delete(f'{grafanaapiurl}/orgs/{org.org_id}/users/{user_id}', auth=grafanaauth)
    print(f'User {user_name} removed from org {org.org_id}')
    resp.raise_for_status()

def update_user_role(u, uid, org, role):
    data = {'role': role}
    resp = requests.patch(f'{grafanaapiurl}/orgs/{org.org_id}/users/{uid}', auth=grafanaauth, json=data)
    print(f'User {u.user_name} id {uid} set role {role} in org {org.org_id}')
    resp.raise_for_status()

def create_user(u, org):
    data = {
        'login': u.user_name,
        'email': u.email,
        'name': f'{u.first_name} {u.last_name}',
        'password': secrets.token_hex(16),
        'orgId': org.org_id
    }
    resp = requests.post(f'{grafanaapiurl}/admin/users', auth=grafanaauth, json=data)
    if resp.status_code != 412:
        print(f'User {u.user_name} in org {org.org_id}')
        resp.raise_for_status()

def switch_org(org):
    resp = requests.post(f'{grafanaapiurl}/user/using/{org.org_id}', auth=grafanaauth)
    resp.raise_for_status()

def get_token_id(name):
    resp = requests.get(f'{grafanaapiurl}/auth/keys', auth=grafanaauth)
    resp.raise_for_status()
    for k in resp.json():
        if k['name'] == name:
            return k['id']
    return None

def delete_token(id):
    resp = requests.delete(f'{grafanaapiurl}/auth/keys/{id}', auth=grafanaauth)
    resp.raise_for_status()

def create_token_auth_header(org):
    name = 'mluviisync'
    exid = get_token_id(name)
    if exid is not None:
        delete_token(exid)
    data = {'name':name, 'role': 'Admin'}
    resp = requests.post(f'{grafanaapiurl}/auth/keys', auth=grafanaauth, json=data)
    resp.raise_for_status()
    token = resp.json()['key']
    tokenauth = {'Authorization': f'Bearer {token}'}
    org_id = get_current_org_id(tokenauth)
    if org.org_id != org_id:
        raise Exception(f'Auth token assigned to wrong organization {org_id}, should be {org.org_id}')
    return tokenauth

def sync_datasource(org, tokenauth):
    dsurl, dstoken = get_datasource_url_and_token(org)
    if dstoken is None:
        return
    name = 'InfluxDB'
    if not has_datasource(name):
        create_datasource(org, name, dsurl, dstoken, tokenauth)

def get_datasource_url_and_token(org):
    resp = requests.get(f'{mluviiapiurl}/Companies/{org.company_id}/metricSettings', headers=mluviiauth)
    if resp.status_code == 404:
        return None, None
    resp.raise_for_status()
    return resp.json()["databaseUrl"], resp.json()["databaseToken"]

def has_datasource(name):
    resp = requests.get(f'{grafanaapiurl}/datasources', auth=grafanaauth)
    resp.raise_for_status()
    for ds in resp.json():
        if ds['name'] == name:
            return True
    return False

def get_current_org_id(tokenauth):
    resp = requests.get(f'{grafanaapiurl}/org', headers=tokenauth)
    resp.raise_for_status()
    return resp.json()['id']

def create_datasource(org, name, dsurl, dstoken, tokenauth):
    data = {
        'name': name,
        'type': 'influxdb',
        'typeName': 'InfluxDB',
        'typeLogoUrl': 'public/app/plugins/datasource/influxdb/img/influxdb_logo.svg',
        'access': 'proxy',
        'url': dsurl,
        'password': '',
        'user': '',
        'database': '',
        'basicAuth': True,
        'isDefault': True,
        'jsonData': {
            'defaultBucket': 'mluvii_realtime',
            'httpMode': 'POST',
            'organization': f'company_{org.company_id}',
            'version': 'Flux'
        },
        'secureJsonData': {
            'token': dstoken
        },
        'readOnly': True
    }
    resp = requests.post(f'{grafanaapiurl}/datasources', headers=tokenauth, json=data)
    if resp.status_code == 409:
        return
    print(f'Data source InfluxDB in org {org.org_id}')
    resp.raise_for_status()
    created_in_org_id = resp.json()['datasource']['orgId']
    if created_in_org_id != org.org_id:
        raise Exception(f'Datasource intended for organization {org.org_id} created in {created_in_org_id}') # fear is the mind killer

def sync_home_dashboard(org, tokenauth):
    f = open(homedashboardfile,)
    dash = json.load(f)
    dash['uid'] = f'mluviihome{org.company_id}'
    dash['title'] = org.name
    for panel in dash['panels']:
        if 'configuredDashboardList' in panel and panel['configuredDashboardList']:
            panel['options']['content'] = generate_dashboard_links(org)
    data = {
        'dashboard': dash,
        'overwrite': True
    }
    resp = requests.post(f'{grafanaapiurl}/dashboards/db', headers=tokenauth, json=data)
    resp.raise_for_status()
    dashid = resp.json()['id']
    set_home_dashboard(org, dashid, tokenauth)

def generate_dashboard_links(org):
    resp = requests.get(f'{mluviiapiurl}/MetricDashboards?companyId={org.company_id}', headers=mluviiauth)
    resp.raise_for_status()
    html = "<ul>\n"
    for d in resp.json():
        name = d["name"]
        key = d["key"]
        html = html + f"""
<li style=\"display:flex; background: rgb(34, 37, 43); padding: 7px; margin: 3px;\">
<a style=\"display:flex; width: 100%;\" href=\"/dashboard/script/mluvii.js?key={key}&orgId={org.org_id}\">{name}</a>
</li>
"""
    return html + "</ul>"

def set_home_dashboard(org, dashid, tokenauth):
    data = {
        'homeDashboardId': dashid
    }
    resp = requests.put(f'{grafanaapiurl}/org/preferences', headers=tokenauth, json=data)
    resp.raise_for_status()

def sync_roles(org, users):
    existing_users = get_org_users(org)
    if not grafanaadmin in existing_users:
        add_user_to_org(grafanaadmin, org, 'Admin')
    for _, u in users.items():
        if u.company_id != org.company_id and not u.is_admin:
            continue
        role = 'Editor'
        if u.user_name in existing_users and existing_users[u.user_name]['role'] != role:
            update_user_role(u, existing_users[u.user_name]['userId'], org, role)
        elif not u.user_name in existing_users:
            add_user_to_org(u.user_name, org, role)
    for ex, exu in existing_users.items():
        if ex == grafanaadmin:
            continue
        if not ex in users or (users[ex].company_id != org.company_id and not users[ex].is_admin):
            remove_user_from_org(ex, exu['userId'], org)

if __name__ == '__main__':
    companyids = parse_arguments()
    print (f'Will sync companies {companyids}' if companyids is not None else 'Will sync company based on the api client id')
    orgs = sync_orgs(companyids)
    allusers = {}
    for _, org in orgs.items():
        users = get_mluvii_users(org)
        allusers.update(users)
        sync_org(org, users)
    for _, org in orgs.items():
        sync_roles(org, allusers)

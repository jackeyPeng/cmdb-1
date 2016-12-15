from asset.models import *
from asset import models
import os,time,commands,json,requests
from salt.client import LocalClient
from logs.models import goLog
from celery.task import task
import xmlrpclib
from salt_api.api import SaltApi

salt_api = SaltApi()

def notification(hostname,project,result,username):
    url = 'http://dlog.65dg.me/dlog'
    headers = {'Content-Type': 'application/json'}
    hs = str(hostname) + " by " + str(username)

    try:
        if type(result) == dict:
            if result.values()[0].find('ERROR') > 0 or result.values()[0].find('error') > 0 or result.values()[0].find('Skip') > 0:
                errmsg = 'Failed'
            else:
                errmsg = 'Success'
        elif type(result) == list:
            result = str(result)
            if result.find('ERROR') > 0 or result.find('error') > 0 or result.find('Skip') > 0:
                errmsg = 'Failed'
            else:
                errmsg = 'Success'
        elif type(result) == str:
            if result.find('ERROR') > 0 or result.find('error') > 0 or result.find('Skip') > 0:
                errmsg = 'Failed'
            else:
                errmsg = 'Success'
    except Exception, e:
        print e
        errmsg = 'Failed'

    data ={
        "hostname": hs,
        "ip": "null",
        "project": project,
        "gitcommit": "null",
        "gitmsg": "null",
        "errmsg": errmsg,
        "errcode": True
    }
    print data
    try:
        requests.post(url,headers=headers,data=json.dumps(data),timeout=3)
    except Exception,e:
        print e




def logs(user,ip,action,result):
    goLog.objects.create(user=user, remote_ip=ip, goAction=action, result=result)


class goPublish:
    def __init__(self,env):
        self.env = env
        self.saltCmd = LocalClient()
        self.svnInfo = models.svn.objects.all()


    def getNowTime(self):
        return time.strftime("%Y-%m-%d_%H:%M:%S", time.localtime(time.time()))


    def deployGo(self,name,services,username,ip):

        self.name = name
        self.services = services
        self.username = username
        self.ip = ip
        hostInfo = {}
        result = []



        minionHost = commands.getstatusoutput('salt-key -l accepted')[1].split()[2:]


        groupname = gogroup.objects.all()
        for name in groupname:
            if self.name == name.name:
                for obj in goservices.objects.filter(env=self.env).filter(group_id=name.id):
                    for saltname in minion.objects.filter(id=obj.saltminion_id):
                        saltHost = saltname.saltname
                        if saltHost not in minionHost:
                            notMinion = 'No minions matched the %s host.' % saltHost
                            result.append(notMinion)
                        if self.services == 'all':
                            golist = [obj.name]
                            if hostInfo.has_key(saltHost):
                                for k,v in hostInfo.items():
                                    if k == saltHost:
                                        v.append(obj.name)
                                        hostInfo[saltHost] = v
                            else:
                                hostInfo[saltHost] = golist
                        else:
                            if obj.name == self.services:
                                golist = [self.services]
                                hostInfo[saltHost] = golist

        for host, goname in hostInfo.items():
            for p in self.svnInfo:
                if p.project.name == self.name:
                    deploy_pillar = "pillar=\"{'project':'" + self.name + "'}\""
                    os.system("salt '%s' state.sls logs.gologs %s" % (host, deploy_pillar))
                    currentTime = self.getNowTime()
                    self.saltCmd.cmd('%s' % host, 'cmd.run',['mv %s %s/%s_%s' % (p.executefile, p.movepath,self.name, currentTime)])
                    svn = self.saltCmd.cmd('%s' % host, 'cmd.run', ['svn update --username=%s --password=%s --non-interactive %s' % (p.username, p.password, p.localpath)])
                    result.append(svn)



            allServices = " ".join(goname)
            restart = self.saltCmd.cmd('%s'%host,'cmd.run',['supervisorctl restart %s'%allServices])
            result.append(restart)


            ding = notification(host,self.name,restart,self.username)


        action = 'deploy ' + self.name
        logs(self.username,self.ip,action,result)


        return result

    def go_revert(self,project,revertFile,host,username,ip):

        self.project = project
        self.revertFile = revertFile
        self.host = host
        self.username = username
        self.ip = ip
        result = []

        for p in self.svnInfo:
            if p.project.name == self.project:
                currentTime = self.getNowTime()
                rename = p.revertpath + '_revert_' + currentTime
                runCmd = "'mv " + p.executefile + " " + rename + "'"


                os.system("salt %s state.sls logs.revert" % self.host)
                self.saltCmd.cmd('%s' % self.host,'cmd.run',['%s' % runCmd])
                revertResult = commands.getstatusoutput("salt '%s' cmd.run 'cp %s/%s %s'" %(self.host,p.movepath,self.revertFile,p.executefile))

                if revertResult[0] == 0:
                    for obj in goservices.objects.filter(env=self.env):
                        if obj.group.name == self.project and self.host == obj.saltminion.saltname:
                            restart = self.saltCmd.cmd('%s' % self.host,'cmd.run',['supervisorctl restart %s' % obj.name])
                            result.append(restart)

                    mes = 'revert to %s version is successful.' % revertFile
                    #mes = {self.host:mes}
                    #result.append(mes)
                else:
                    mes = 'revert to %s version is failed.' % revertFile

                mes = {self.host: mes}
                info = 'revert ' + self.project
                ding = notification(self.host,info,mes,username)

                result.append(mes)

        action = 'revert ' + self.project
        logs(self.username, self.ip, action, result)
        return result


    def goConf(self,project,usernmae,ip):
        self.project = project
        self.username = usernmae
        self.ip = ip
        result = []
        conf = goconf.objects.all()



        for p in conf:
            try:
                if str(p.env) == self.env and p.project.name == self.project:
                    #print p.username,p.password,p.localpath,p.hostname
                    confCmd = "svn update --username=%s --password=%s --non-interactive %s" %(p.username,p.password,p.localpath)
                    confResult = self.saltCmd.cmd('%s' % p.hostname,'cmd.run',['%s' % confCmd])
                    result.append(confResult)

                    info = self.project + ' conf'

                    ding = notification(p.hostname, info, confResult, self.username)
            except Exception,e:
                print e
        action = 'conf ' + self.project
        logs(self.username, self.ip, action, result)


        return result


    def build_go(self,hostname,project,supervisorName,goCommand,svnRepo,svnUsername,svnPassword,fileName,username,ip):
        self.hostname = hostname
        self.project = project
        self.supervisorName = supervisorName
        self.goCommand = goCommand
        self.svnRepo = svnRepo
        self.svnUsername = svnUsername
        self.svnPassword = svnPassword
        self.fileName = fileName
        self.username = username
        self.ip =  ip

        f = open(self.fileName,'w')
        f.write("start....")
        f.write('\n\n\n\n')
        f.flush()
        #result = self.saltCmd.cmd(self.hostname, 'state.sls', kwarg={
        #    'mods': 'goservices.supervisor_submodule',
        #    'pillar': {
        #        'goprograme': self.project,
        #        'supProgrameName': self.supervisorName,
        #        'goRunCommand': self.goCommand,
        #        'svnrepo': self.svnRepo,
        #        'svnusername': self.svnUsername,
        #        'svnpassword': self.svnPassword,
        #    },
        #})
        try:
            pillar= " pillar=\"{'goprograme': '%s','supProgrameName': '%s','goRunCommand': '%s','svnrepo': '%s','svnusername': '%s','svnpassword': '%s'}\"" % (self.project,self.supervisorName,self.goCommand,self.svnRepo,self.svnUsername,self.svnPassword)
            deploy_cmd = "salt " + self.hostname +  " state.sls queue=True goservices.supervisor_submodule " + pillar
            s, result = commands.getstatusoutput(deploy_cmd)
            f.write(result)
            f.write('\n\n\n\n')
            f.write('done')
            f.close()
            if result.find('Failed:    0') < 0:
                notification(self.hostname,'add ' + self.project + ' service','is error',self.username)
                logs(self.username,self.ip,'add ' + self.project + ' service' ,'Failed')
            else:
                notification(self.hostname, 'add ' + self.project + ' service', 'successful', self.username)
                logs(self.username, self.ip,'add ' + self.project + ' service', 'Successful')
        except Exception, e:
            print e
            return 'error'

        return result


class goServicesni:
    def __init__(self,projectName):
        self.projectName = projectName

    def getServiceName(self):
        services = []
        groupname = gogroup.objects.all()
        for group in groupname:
            if self.projectName == group.name:
                for obj in goservices.objects.filter(group=group.id):
                    services.append(obj)

        return services





def syncAsset():
    salt = LocalClient()
    grains = salt.cmd('*','grains.items')
    obj = Asset.objects.all()
    host_list = []
    for i in obj:
        host_list.append(i.hostname)


    try:
        for host in grains.keys():
            ip = grains[host]['ipv4'][-1]
            hostname_id = grains[host]['id']
            cpu = grains[host]['cpu_model']
            memory = grains[host]['mem_total']
            if grains[host].has_key('virtual'):
                asset_type = grains[host]['virtual']
            else:
                asset_type = 'physical'
            if grains[host].has_key('osfinger'):
                os = grains[host]['osfinger']
            else:
                os = grains[host]['osfullname']


            if host not in host_list:
                try:
                    Asset.objects.create(ip=ip,hostname=hostname_id,system_type=os,cpu=cpu,memory=memory,asset_type=asset_type)
                except Exception,e:
                    print e
    except Exception,e:
        print e



class go_monitor_status(object):
    def get_hosts(self):
        obj = gostatus.objects.all()
        return obj

    def get_supervisor_status(self,hostname_id):
        self.hostname_id = hostname_id
        obj = gostatus.objects.all().filter(hostname_id=self.hostname_id)
        for info in obj:
            try:
                s = xmlrpclib.Server('http://%s:%s@%s:%s/RPC2' % (info.supervisor_username,info.supervisor_password,info.supervisor_host,info.supervisor_port))
                status = s.supervisor.getAllProcessInfo()
            except Exception, e:
                print e
                return 0

        return status

class crontab_svn_status(object):
    def __init__(self,login_user,ip):
        self.login_user = login_user
        self.ip = ip
    def get_crontab_list(self):
        obj = crontab_svn.objects.all()
        return obj

    def crontab_svn_update(self,hostname,username,password,localpath,project):
        self.hostname = hostname
        self.username = username
        self.password = password
        self.localpath = localpath
        self.project = project

        cmd = "svn update --username=%s --password=%s --non-interactive %s" % (self.username, self.password, self.localpath)
        data = {
            'client': 'local',
            'tgt': self.hostname,
            'fun': 'cmd.run',
            'arg': cmd
        }
        result = salt_api.salt_cmd(data)
        if result != 0:
            result = result['return']
        notification(self.hostname,self.project,result,self.login_user)
        logs(self.login_user,self.ip,'update svn',result)
        return result



@task
def deploy_go(env,hostname,project,supervisorName,goCommand,svnRepo,svnUsername,svnPassword,fileName,username,ip):
    obj = goPublish(env)
    obj.build_go(hostname, project, supervisorName, goCommand, svnRepo, svnUsername, svnPassword,fileName,username,ip)

def getNowTime():
    return time.strftime("%Y-%m-%d_%H:%M:%S", time.localtime(time.time()))





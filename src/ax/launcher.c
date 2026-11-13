#define _POSIX_C_SOURCE 200809L
#include <ctype.h>
#include <errno.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/ioctl.h>
#include <sys/stat.h>
#include <sys/un.h>
#include <unistd.h>

#ifndef AX_PYTHON
#error AX_PYTHON must name the installed interpreter
#endif
#ifndef AX_SOCKET
#error AX_SOCKET must name the installed local socket
#endif
#ifndef AX_CONFIG_FILE
#define AX_CONFIG_FILE ""
#endif
#ifndef AX_CONFIG_MTIME
#define AX_CONFIG_MTIME 0
#endif

extern char **environ;
typedef struct { char *data; size_t size,capacity; } Buffer;
static void append(Buffer *b,const char *s,size_t n) {
    if (b->size+n+1>b->capacity) {
        b->capacity=(b->size+n+1)*2;
        char *p=realloc(b->data,b->capacity);
        if (!p) { fputs("ax: out of memory\n",stderr); exit(1); }
        b->data=p;
    }
    memcpy(b->data+b->size,s,n); b->size+=n; b->data[b->size]=0;
}
static void literal(Buffer *b,const char *s) { append(b,s,strlen(s)); }
static void quoted(Buffer *b,const char *s,size_t n) {
    literal(b,"\"");
    for (size_t i=0;i<n;i++) {
        unsigned char c=(unsigned char)s[i];
        if (c=='"'||c=='\\') { char pair[2]={'\\',(char)c}; append(b,pair,2); }
        else if (c<32) { char escaped[7]; snprintf(escaped,sizeof escaped,"\\u%04x",c);literal(b,escaped); }
        else append(b,(char *)&c,1);
    }
    literal(b,"\"");
}
static void string(Buffer *b,const char *s) { quoted(b,s,strlen(s)); }
static void python(int argc,char **argv) {
    char **args=calloc((size_t)argc+3,sizeof(char *));
    if (!args) exit(1);
    args[0]=AX_PYTHON;args[1]="-m";args[2]="ax";
    for (int i=1;i<argc;i++) args[i+2]=argv[i];
    execv(AX_PYTHON,args);perror("ax: Python entry point");exit(127);
}
static char *value_start(char *text,const char *key) {
    char *p=strstr(text,key);
    if (!p) return NULL;
    p+=strlen(key);while(isspace((unsigned char)*p))p++;
    if (*p++!=':')return NULL;
    while(isspace((unsigned char)*p))p++;
    return p;
}

int main(int argc,char **argv) {
    if(argc<2||strcmp(argv[1],"run"))python(argc,argv);
    const char *configured=getenv("AX_CONFIG");
    if(configured){char *resolved=realpath(configured,NULL);if(!resolved||strcmp(resolved,AX_CONFIG_FILE))python(argc,argv);free(resolved);}
    struct stat config_stat;
    time_t modified=stat(AX_CONFIG_FILE,&config_stat)==0?config_stat.st_mtime:0;
    if(modified!=AX_CONFIG_MTIME)python(argc,argv);
    const char *claude=getenv("CLAUDE_CODE_SESSION_ID"),*codex=getenv("CODEX_THREAD_ID");
    if((claude&&codex)||(!claude&&!codex))python(argc,argv);
    int detached=0,every=10,index=2;
    const char *description=NULL;
    while(index<argc) {
        if(!strcmp(argv[index],"--")){index++;break;}
        if(!strcmp(argv[index],"--detach")){detached=1;index++;continue;}
        if(!strcmp(argv[index],"--description")&&index+1<argc){description=argv[index+1];index+=2;continue;}
        if(!strcmp(argv[index],"--every")&&index+1<argc){
            char *end=NULL;long number=strtol(argv[index+1],&end,10);
            if(!end||*end||number<10||number>60)python(argc,argv);
            every=(int)number;index+=2;continue;
        }
        if(argv[index][0]=='-')python(argc,argv);
        break;
    }
    if(index>=argc)python(argc,argv);
    int fd=socket(AF_UNIX,SOCK_STREAM,0);
    if(fd<0)python(argc,argv);
    struct sockaddr_un addr={0};addr.sun_family=AF_UNIX;
    if(strlen(AX_SOCKET)>=sizeof addr.sun_path){close(fd);python(argc,argv);}
    strcpy(addr.sun_path,AX_SOCKET);
    if(connect(fd,(struct sockaddr *)&addr,sizeof addr)){close(fd);python(argc,argv);}
    /* After dispatch begins, never replay through the fallback. */
    struct timeval timeout={10,0};setsockopt(fd,SOL_SOCKET,SO_RCVTIMEO,&timeout,sizeof timeout);
    setsockopt(fd,SOL_SOCKET,SO_SNDTIMEO,&timeout,sizeof timeout);
    char *cwd=getcwd(NULL,0);
    if(!cwd){close(fd);python(argc,argv);}
    int terminal=isatty(STDIN_FILENO)&&isatty(STDOUT_FILENO);
    if(terminal){struct winsize size;if(ioctl(STDIN_FILENO,TIOCGWINSZ,&size)==0){char rows[16],columns[16];snprintf(rows,sizeof rows,"%u",size.ws_row);snprintf(columns,sizeof columns,"%u",size.ws_col);setenv("LINES",rows,1);setenv("COLUMNS",columns,1);}}
    if(detached&&!terminal)setenv("AX_STDIN_CLOSED","1",1);
    Buffer b={0},purpose={0};
    if(!description){for(int i=index;i<argc;i++){if(i>index)literal(&purpose," ");literal(&purpose,argv[i]);}description=purpose.data;}
    literal(&b,"{\"operation\":\"task.create\",\"args\":{\"kind\":\"run\",\"caller\":");
    Buffer owner={0};literal(&owner,claude?"claude:":"codex:");literal(&owner,claude?claude:codex);string(&b,owner.data);
    literal(&b,",\"launcher\":\"native\",\"purpose\":");string(&b,description);
    literal(&b,",\"cwd\":");string(&b,cwd);
    char number[64];snprintf(number,sizeof number,",\"every\":%d,\"tty\":%s",every,terminal?"true":"false");literal(&b,number);
    if(claude){
        const char *inbox=getenv("CLAUDE_CODE_MESSAGING_SOCKET"),*token=getenv("CLAUDE_CODE_MESSAGING_TOKEN");
        if(inbox){literal(&b,",\"inbox\":");string(&b,inbox);}
        if(token){literal(&b,",\"inbox_token\":");string(&b,token);}
    }
    literal(&b,",\"command\":[");
    for(int i=index;i<argc;i++){if(i>index)literal(&b,",");string(&b,argv[i]);}
    literal(&b,"],\"environment\":{");
    int first=1;
    for(char **entry=environ;*entry;entry++){
        char *eq=strchr(*entry,'=');if(!eq)continue;
        if(!first)literal(&b,",");first=0;
        quoted(&b,*entry,(size_t)(eq-*entry));literal(&b,":");string(&b,eq+1);
    }
    literal(&b,"}}}\n");
    size_t sent=0;
    while(sent<b.size){ssize_t n=write(fd,b.data+sent,b.size-sent);if(n<0&&errno==EINTR)continue;if(n<=0){fputs("ax: dispatch outcome unknown; inspect ax task list before retrying\n",stderr);return 1;}sent+=(size_t)n;}
    Buffer response={0};char chunk[8192];
    while(!response.data||!strchr(response.data,'\n')){
        ssize_t n=read(fd,chunk,sizeof chunk);if(n<0&&errno==EINTR)continue;
        if(n<=0||response.size+(size_t)n>2097152){fputs("ax: dispatch outcome unknown; inspect ax task list before retrying\n",stderr);return 1;}
        append(&response,chunk,(size_t)n);
    }
    close(fd);
    char *ok=value_start(response.data,"\"ok\"");
    if(!ok||strncmp(ok,"true",4)){fputs(response.data,stderr);return 1;}
    char *result=value_start(response.data,"\"result\""),*id=result?value_start(result,"\"id\""):NULL;
    char task_id[13]={0};
    if(!id||*id++!='"'){fputs("ax: task created but id unavailable; inspect ax task list\n",stderr);return 1;}
    for(int i=0;i<12;i++){if(!isxdigit((unsigned char)id[i])){fputs("ax: invalid task id\n",stderr);return 1;}task_id[i]=id[i];}
    if(id[12]!='"')return 1;
    if(detached){printf("{\"id\":\"%s\",\"detached\":true}\n",task_id);return 0;}
    execl(AX_PYTHON,AX_PYTHON,"-m","ax","attach",task_id,(char *)NULL);
    perror("ax: attach");return 127;
}

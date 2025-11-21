export type MeetingStatus = 'queued' | 'processing' | 'completed' | 'failed';

export type TaskStatus = 'draft' | 'approved' | 'rejected';

export interface Meeting {
    id: string;
    title: string;
    startedAt: string;
    status: MeetingStatus;
    draftTaskCount: number;
}

export type IssueType = 'Story' | 'Task' | 'Bug' | 'Spike';

export type Priority = 'Low' | 'Medium' | 'High';

export interface Task {
    id: string;
    meetingId: string;
    summary: string;
    description?: string;
    issueType: IssueType;
    priority: Priority;
    storyPoints?: number;
    assigneeId?: string;
    assigneeName?: string;
    assigneeAccountId?: string;
    labels: string[];
    status: TaskStatus;
    sourceQuote?: string;
    jiraIssueKey?: string | null;
    jiraIssueUrl?: string | null;
    pushedToJiraAt?: string | null;
}

export interface User {
    id: string;
    displayName: string;
    email?: string;
    jiraAccountId?: string;
    voiceSamplePath?: string;
}

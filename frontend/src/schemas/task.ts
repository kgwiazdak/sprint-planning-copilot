import {z} from 'zod';

export const issueTypeOptions = ['Story', 'Task', 'Bug', 'Spike'] as const;
export const priorityOptions = ['Low', 'Medium', 'High'] as const;
export const taskStatusOptions = ['draft', 'approved', 'rejected'] as const;

export const TaskSchema = z.object({
    id: z.string().optional(),
    meetingId: z.string(),
    summary: z.string().min(3, 'Summary must be at least 3 characters'),
    description: z.string().optional(),
    issueType: z.enum(issueTypeOptions),
    priority: z.enum(priorityOptions),
    storyPoints: z
        .number()
        .int('Story points must be an integer')
        .positive('Story points must be positive')
        .optional(),
    assigneeId: z.string().optional(),
    status: z.enum(taskStatusOptions),
    sourceQuote: z.string().optional(),
});

export const TaskUpdateSchema = TaskSchema.pick({
    summary: true,
    description: true,
    issueType: true,
    priority: true,
    storyPoints: true,
    assigneeId: true,
    status: true,
});

export const InlineTaskUpdateSchema = TaskUpdateSchema.partial();

export type TaskFormValues = z.infer<typeof TaskSchema>;
export type TaskUpdateValues = z.infer<typeof TaskUpdateSchema>;
